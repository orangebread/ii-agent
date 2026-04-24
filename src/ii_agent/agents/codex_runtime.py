from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel

from ii_agent.agents.models.message import Message
from ii_agent.agents.models.response import ToolExecution
from ii_agent.agents.runs.agent import (
    ReasoningDeltaEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentDeltaEvent,
    RunErrorEvent,
    RunPausedEvent,
    RunStartedEvent,
)
from ii_agent.agents.runs.requirement import RunRequirement
from ii_agent.agents.sandboxes import Sandbox
from ii_agent.agents.sandboxes.terminal import LiveTerminalHandle
from ii_agent.agents.tools.base import ImageContent, TextContent, ToolResult, UserInputField
from ii_agent.core.config.llm_config import LLMConfig
from ii_agent.core.container import get_app_container
from ii_agent.core.db import get_db_session_local
from ii_agent.core.logger import logger
from ii_agent.core.redis.cancel import (
    RunCancelledException,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from ii_agent.files import File, Image
from ii_agent.tasks.schemas import CodexResumeCheckpoint


_CODEX_METADATA_KEY = "codex_runtime"
_WORKSPACE_CWD = "/workspace"
_THREAD_APPROVAL_POLICY = "untrusted"
_THREAD_SANDBOX = "workspace-write"
_TERMINAL_ENVS = {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
}
_REQUEST_TIMEOUT_SECONDS = 30.0
_RESUME_REQUEST_TIMEOUT_SECONDS = 10.0
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_SHELL_PROMPT_RE = re.compile(r"^[^\s@]+@[^\s:]+:[^\s]+[#$]$")


def _app_server_bootstrap_command() -> str:
    return (
        "stty -echo -icanon min 1 time 0; "
        "source /app/.user_env.sh >/dev/null 2>&1 || true; "
        "exec codex app-server --listen stdio://\n"
    )


def _normalize_pty_log_line(line: str) -> str | None:
    clean_line = _ANSI_ESCAPE_RE.sub("", line).strip()
    if not clean_line:
        return None
    if "exec codex app-server --listen stdio://" in clean_line:
        return None
    if _SHELL_PROMPT_RE.fullmatch(clean_line):
        return None
    try:
        json.loads(clean_line)
    except json.JSONDecodeError:
        return clean_line
    return None


def _stringify_input(value: Any) -> str:
    """Normalize the agent input into plain text for Codex."""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json(exclude_none=True)
    if isinstance(value, Message):
        return json.dumps(value.to_dict())
    if isinstance(value, list) and value and isinstance(value[0], Message):
        return json.dumps([message.to_dict() for message in value])
    return json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)


def _extract_text(value: Any) -> str:
    """Best-effort text extraction from app-server notifications."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("delta", "text", "message"):
            text = value.get(key)
            if isinstance(text, str):
                return text
        if "item" in value:
            return _extract_text(value["item"])
        content = value.get("content")
        if isinstance(content, list):
            return "".join(_extract_text(item) for item in content)
    if isinstance(value, list):
        return "".join(_extract_text(item) for item in value)
    return ""


def _is_reasoning_method(method: str) -> bool:
    lowered = method.lower()
    return "reason" in lowered or "thought" in lowered


def _is_agent_message_delta(method: str) -> bool:
    lowered = method.lower()
    return lowered == "item/agentmessage/delta" or lowered == "item/plan/delta"


def _is_approval_request(method: str) -> bool:
    return method.endswith("requestApproval")


def _is_user_input_request(method: str) -> bool:
    return method.endswith("requestUserInput") or method == "mcpServer/elicitation/request"


@dataclass
class _CodexBinding:
    thread_id: str
    model: str | None = None
    last_turn_id: str | None = None
    dynamic_tool_fingerprint: str | None = None

    @classmethod
    def from_session_metadata(cls, session_metadata: dict[str, Any] | None) -> _CodexBinding | None:
        if not isinstance(session_metadata, dict):
            return None
        binding_raw = session_metadata.get(_CODEX_METADATA_KEY)
        if not isinstance(binding_raw, dict):
            return None
        thread_id = binding_raw.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        model = binding_raw.get("model")
        last_turn_id = binding_raw.get("last_turn_id")
        dynamic_tool_fingerprint = binding_raw.get("dynamic_tool_fingerprint")
        return cls(
            thread_id=thread_id,
            model=model if isinstance(model, str) else None,
            last_turn_id=last_turn_id if isinstance(last_turn_id, str) else None,
            dynamic_tool_fingerprint=dynamic_tool_fingerprint
            if isinstance(dynamic_tool_fingerprint, str)
            else None,
        )

    def into_session_metadata(self, session_metadata: dict[str, Any] | None) -> dict[str, Any]:
        updated_metadata = dict(session_metadata or {})
        updated_metadata[_CODEX_METADATA_KEY] = {
            "thread_id": self.thread_id,
            "model": self.model,
            "last_turn_id": self.last_turn_id,
            "dynamic_tool_fingerprint": self.dynamic_tool_fingerprint,
        }
        return updated_metadata


class _CodexRpcError(RuntimeError):
    """Raised when the Codex app-server rejects a JSON-RPC request."""


@dataclass
class _CodexServerRequest:
    raw_id: Any
    method: str
    params: dict[str, Any]

    @property
    def request_id(self) -> str:
        return str(self.raw_id)


@dataclass
class _DynamicToolCallOutcome:
    response: dict[str, Any]
    should_stop: bool = False
    content: str = ""


class _CodexAppServerSession:
    """Minimal JSON-RPC client over a sandbox PTY."""

    def __init__(self, *, handle: LiveTerminalHandle) -> None:
        self._handle = handle
        self._loop = asyncio.get_running_loop()
        self._buffer = ""
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._pending_methods: dict[int, str] = {}
        self._events: asyncio.Queue[tuple[str, dict[str, Any] | _CodexServerRequest]] = (
            asyncio.Queue()
        )
        self._request_id = 0
        self._raw_lines: deque[str] = deque(maxlen=25)

    def feed_data(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line.rstrip("\r"))

    def _handle_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            self._raw_lines.append(stripped)
            return
        self._dispatch(payload)

    def _dispatch(self, payload: dict[str, Any]) -> None:
        if "id" in payload and ("result" in payload or "error" in payload):
            try:
                request_id = int(payload["id"])
            except (TypeError, ValueError):
                self._raw_lines.append(json.dumps(payload))
                return

            future = self._pending.pop(request_id, None)
            self._pending_methods.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(payload)
            return

        if "method" in payload and "id" in payload:
            method = str(payload.get("method") or "")
            request_id_raw = payload.get("id")
            try:
                echoed_request_id = int(request_id_raw)
            except (TypeError, ValueError):
                echoed_request_id = None
            if (
                echoed_request_id is not None
                and self._pending_methods.get(echoed_request_id) == method
            ):
                return

            params = payload.get("params")
            self._events.put_nowait(
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id=request_id_raw,
                        method=method,
                        params=params if isinstance(params, dict) else {},
                    ),
                )
            )
            return

        if "method" in payload:
            self._events.put_nowait(("notification", payload))
            return

        self._raw_lines.append(json.dumps(payload))

    async def _send(self, payload: dict[str, Any]) -> None:
        await self._handle.send_input((json.dumps(payload, separators=(",", ":")) + "\n").encode())

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[request_id] = future
        self._pending_methods[request_id] = method

        payload: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            payload["params"] = params

        await self._send(payload)

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            self._pending_methods.pop(request_id, None)
            diagnostics = "\n".join(self._raw_lines) or "No app-server output received."
            raise RuntimeError(
                f"Timed out waiting for Codex app-server response to {method}.\n{diagnostics}"
            ) from exc

        if "error" in response:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise _CodexRpcError(f"{method} failed: {message}")

        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def next_event(
        self, *, timeout: float = 0.25
    ) -> tuple[str, dict[str, Any] | _CodexServerRequest] | None:
        try:
            return await asyncio.wait_for(self._events.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def respond(self, request_id: Any, *, result: Any = None, error: Any = None) -> None:
        payload: dict[str, Any] = {"id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = {} if result is None else result
        await self._send(payload)

    def debug_output(self) -> str:
        return "\n".join(self._raw_lines)


class _CodexPtyLogMirror:
    """Mirror non-JSON PTY output into backend logs for local debugging."""

    def __init__(self, *, session_id: str, run_id: str) -> None:
        self._session_id = session_id
        self._run_id = run_id
        self._buffer = ""

    def feed_data(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line.rstrip("\r"))

    def _handle_line(self, line: str) -> None:
        normalized = _normalize_pty_log_line(line)
        if normalized is None:
            return
        logger.info(f"[codex-pty][session={self._session_id}][run={self._run_id}] {normalized}")


class CodexRuntimeAgent:
    """Runtime agent backed by ``codex app-server`` over sandbox stdio."""

    def __init__(
        self,
        *,
        user_id: str,
        session_id: str,
        llm_config: LLMConfig,
        name: str,
        system_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.llm_config = llm_config
        self.name = name
        self.system_message = system_message
        self.metadata = metadata
        self.id: str | None = None
        self.sandbox: Sandbox | None = None
        self._tools: dict[str, Any] = {}

    def set_id(self) -> None:
        if self.id is None:
            self.id = f"{self.name}-{self.session_id}"

    def add_tool(self, tool: Any) -> None:
        tool_name = getattr(tool, "name", None)
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Codex dynamic tools must define a non-empty name")
        self._tools[tool_name] = tool

    def acontinue_run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        run_id = kwargs.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("Codex continue_run requires a run_id")

        resume_checkpoint = kwargs.get("resume_checkpoint")
        if not isinstance(resume_checkpoint, CodexResumeCheckpoint):
            raise ValueError("Codex continue_run requires a Codex resume checkpoint")

        decision = kwargs.get("decision")
        if not isinstance(decision, str) or not decision:
            raise ValueError("Codex continue_run requires a resolved decision")

        policy_patch = kwargs.get("policy_patch")
        user_input = kwargs.get("user_input")

        return self._acontinue_run_stream(
            run_id=run_id,
            resume_checkpoint=resume_checkpoint,
            decision=decision,
            user_input=user_input if isinstance(user_input, dict) else {},
            policy_patch=policy_patch if isinstance(policy_patch, dict) else None,
        )

    async def arun(
        self,
        input: str | list | dict | Message | BaseModel | list[Message],
        *,
        run_id: str | None = None,
        stream: bool = True,
        images: Sequence[Image] | None = None,
        files: Sequence[File] | None = None,
        **_: Any,
    ) -> AsyncIterator[Any]:
        if not stream:
            raise RuntimeError("Codex runtime agent currently supports only streaming runs.")
        return self._arun_stream(
            input=input,
            run_id=run_id or str(uuid4()),
            images=images,
            files=files,
        )

    async def _arun_stream(
        self,
        *,
        input: str | list | dict | Message | BaseModel | list[Message],
        run_id: str,
        images: Sequence[Image] | None,
        files: Sequence[File] | None,
    ) -> AsyncIterator[Any]:
        await register_run(run_id)

        sandbox: Sandbox | None = None
        rpc: _CodexAppServerSession | None = None
        handle: LiveTerminalHandle | None = None
        thread_binding: _CodexBinding | None = None
        current_thread_id: str | None = None
        current_turn_id: str | None = None
        content_parts: list[str] = []
        last_error_message: str | None = None
        interrupt_requested = False

        try:
            sandbox = await self._ensure_sandbox()

            yield RunStartedEvent(
                agent_id=self.id or "",
                agent_name=self.name,
                run_id=run_id,
                session_id=self.session_id,
                model=self.llm_config.model,
                model_provider=self.llm_config.provider,
            )

            handle, rpc = await self._start_app_server(sandbox, run_id=run_id)
            thread_binding = await self._load_thread_binding()
            current_thread_id, thread_binding = await self._start_or_resume_thread(
                rpc=rpc,
                binding=thread_binding,
            )

            prompt_text = self._build_prompt_text(input=input, files=files)
            turn_result = await rpc.request(
                "turn/start",
                self._build_turn_params(
                    thread_id=current_thread_id,
                    prompt_text=prompt_text,
                    images=images,
                ),
            )
            turn = turn_result.get("turn")
            if isinstance(turn, dict) and isinstance(turn.get("id"), str):
                current_turn_id = turn["id"]
                thread_binding.last_turn_id = current_turn_id
                await self._persist_thread_binding(thread_binding)

            while True:
                await raise_if_cancelled(run_id)

                event_entry = await rpc.next_event()
                if event_entry is None:
                    continue
                event_kind, payload = event_entry

                if event_kind == "server_request":
                    server_request = payload
                    if not isinstance(server_request, _CodexServerRequest):
                        continue

                    if _is_approval_request(server_request.method):
                        checkpoint = self._build_approval_checkpoint(
                            request=server_request,
                            fallback_thread_id=current_thread_id or "",
                            fallback_turn_id=current_turn_id,
                        )
                        await self._persist_codex_resume_checkpoint(
                            run_id=run_id,
                            checkpoint=checkpoint,
                        )
                        yield self._create_codex_approval_pause_event(
                            run_id=run_id,
                            request=server_request,
                        )
                        return

                    if server_request.method == "item/tool/call":
                        outcome = await self._execute_dynamic_tool_call(request=server_request)
                        await rpc.respond(server_request.raw_id, result=outcome.response)
                        if outcome.should_stop:
                            yield RunCompletedEvent(
                                agent_id=self.id or "",
                                agent_name=self.name,
                                run_id=run_id,
                                session_id=self.session_id,
                                model=self.llm_config.model,
                                model_provider=self.llm_config.provider,
                                content=outcome.content,
                            )
                            return
                        continue

                    if _is_user_input_request(server_request.method):
                        checkpoint = self._build_user_input_checkpoint(
                            request=server_request,
                            fallback_thread_id=current_thread_id or "",
                            fallback_turn_id=current_turn_id,
                        )
                        await self._persist_codex_resume_checkpoint(
                            run_id=run_id,
                            checkpoint=checkpoint,
                        )
                        yield self._create_codex_user_input_pause_event(
                            run_id=run_id,
                            request=server_request,
                        )
                        return

                    await rpc.respond(
                        server_request.raw_id,
                        error={
                            "code": -32601,
                            "message": f"Unsupported server request: {server_request.method}",
                        },
                    )
                    continue

                notification = payload
                if not isinstance(notification, dict):
                    continue

                method = str(notification.get("method") or "")
                params = notification.get("params")
                params_dict = params if isinstance(params, dict) else {}

                if method == "thread/tokenUsage/updated":
                    continue

                if method == "error":
                    message = _extract_text(params_dict) or "Codex app-server failed."
                    last_error_message = message
                    continue

                if method == "turn/started":
                    turn = params_dict.get("turn")
                    if isinstance(turn, dict) and isinstance(turn.get("id"), str):
                        current_turn_id = turn["id"]
                        thread_binding.last_turn_id = current_turn_id
                        await self._persist_thread_binding(thread_binding)
                    continue

                if _is_agent_message_delta(method):
                    delta_text = _extract_text(params_dict)
                    if delta_text:
                        content_parts.append(delta_text)
                        yield RunContentDeltaEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            content=delta_text,
                        )
                    continue

                if _is_reasoning_method(method) and method.endswith("/delta"):
                    reasoning_delta = _extract_text(params_dict)
                    if reasoning_delta:
                        yield ReasoningDeltaEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            reasoning_content=reasoning_delta,
                        )
                    continue

                if method == "item/completed":
                    item = params_dict.get("item")
                    if isinstance(item, dict) and item.get("type") == "agentMessage":
                        text = item.get("text")
                        if isinstance(text, str) and text and not content_parts:
                            content_parts.append(text)
                    continue

                if method == "turn/completed":
                    turn = params_dict.get("turn")
                    turn_dict = turn if isinstance(turn, dict) else {}
                    status = str(turn_dict.get("status") or "")
                    error = turn_dict.get("error")
                    error_message = (
                        _extract_text(error) or last_error_message or "Codex turn failed."
                    )
                    final_content = "".join(content_parts)

                    if status == "completed":
                        yield RunCompletedEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            content=final_content,
                        )
                        return

                    if status == "interrupted":
                        yield RunCancelledEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            reason="Run was cancelled",
                        )
                        return

                    yield RunErrorEvent(
                        agent_id=self.id or "",
                        agent_name=self.name,
                        run_id=run_id,
                        session_id=self.session_id,
                        model=self.llm_config.model,
                        model_provider=self.llm_config.provider,
                        content=error_message,
                    )
                    return

        except RunCancelledException:
            if (
                rpc is not None
                and current_thread_id is not None
                and current_turn_id is not None
                and not interrupt_requested
            ):
                try:
                    await rpc.request(
                        "turn/interrupt",
                        {"threadId": current_thread_id, "turnId": current_turn_id},
                    )
                except Exception:
                    logger.warning(
                        f"Failed to interrupt Codex turn {current_turn_id}",
                        exc_info=True,
                    )

            yield RunCancelledEvent(
                agent_id=self.id or "",
                agent_name=self.name,
                run_id=run_id,
                session_id=self.session_id,
                model=self.llm_config.model,
                model_provider=self.llm_config.provider,
                reason="Run was cancelled",
            )
        except Exception as exc:
            logger.error(f"Codex runtime run {run_id} failed: {exc}", exc_info=True)
            diagnostics = rpc.debug_output() if rpc is not None else ""
            message = str(exc)
            if diagnostics:
                message = f"{message}\n{diagnostics}"
            yield RunErrorEvent(
                agent_id=self.id or "",
                agent_name=self.name,
                run_id=run_id,
                session_id=self.session_id,
                model=self.llm_config.model,
                model_provider=self.llm_config.provider,
                content=message,
            )
        finally:
            await cleanup_run(run_id)
            if handle is not None:
                try:
                    await handle.kill()
                except Exception:
                    logger.debug("Failed to kill Codex app-server PTY", exc_info=True)
                try:
                    await handle.disconnect()
                except Exception:
                    logger.debug("Failed to disconnect Codex app-server PTY", exc_info=True)

    async def _acontinue_run_stream(
        self,
        *,
        run_id: str,
        resume_checkpoint: CodexResumeCheckpoint,
        decision: str,
        user_input: dict[str, Any],
        policy_patch: dict[str, Any] | None,
    ) -> AsyncIterator[Any]:
        await register_run(run_id)

        sandbox: Sandbox | None = None
        rpc: _CodexAppServerSession | None = None
        handle: LiveTerminalHandle | None = None
        content_parts: list[str] = []
        last_error_message: str | None = None
        resume_deadline = asyncio.get_running_loop().time() + _RESUME_REQUEST_TIMEOUT_SECONDS
        awaiting_resume_request = True

        try:
            sandbox = await self._ensure_sandbox()
            handle, rpc = await self._start_app_server(sandbox, run_id=run_id)
            await self._resume_thread(rpc=rpc, thread_id=resume_checkpoint.thread_id)

            while True:
                await raise_if_cancelled(run_id)

                if awaiting_resume_request and asyncio.get_running_loop().time() >= resume_deadline:
                    raise RuntimeError("Codex did not replay the pending server request on resume.")

                event_entry = await rpc.next_event()
                if event_entry is None:
                    continue
                event_kind, payload = event_entry

                if event_kind == "server_request":
                    server_request = payload
                    if not isinstance(server_request, _CodexServerRequest):
                        continue

                    if awaiting_resume_request and self._matches_resume_checkpoint(
                        request=server_request,
                        checkpoint=resume_checkpoint,
                    ):
                        await rpc.respond(
                            server_request.raw_id,
                            result=self._resume_result_for_checkpoint(
                                request=server_request,
                                checkpoint=resume_checkpoint,
                                decision=decision,
                                policy_patch=policy_patch,
                                user_input=user_input,
                            ),
                        )
                        awaiting_resume_request = False
                        continue

                    if _is_approval_request(server_request.method):
                        checkpoint = self._build_approval_checkpoint(
                            request=server_request,
                            fallback_thread_id=resume_checkpoint.thread_id,
                            fallback_turn_id=resume_checkpoint.turn_id,
                        )
                        await self._persist_codex_resume_checkpoint(
                            run_id=run_id,
                            checkpoint=checkpoint,
                        )
                        yield self._create_codex_approval_pause_event(
                            run_id=run_id,
                            request=server_request,
                        )
                        return

                    if server_request.method == "item/tool/call":
                        outcome = await self._execute_dynamic_tool_call(request=server_request)
                        await rpc.respond(server_request.raw_id, result=outcome.response)
                        if outcome.should_stop:
                            yield RunCompletedEvent(
                                agent_id=self.id or "",
                                agent_name=self.name,
                                run_id=run_id,
                                session_id=self.session_id,
                                model=self.llm_config.model,
                                model_provider=self.llm_config.provider,
                                content=outcome.content,
                            )
                            return
                        continue

                    if _is_user_input_request(server_request.method):
                        checkpoint = self._build_user_input_checkpoint(
                            request=server_request,
                            fallback_thread_id=resume_checkpoint.thread_id,
                            fallback_turn_id=resume_checkpoint.turn_id,
                        )
                        await self._persist_codex_resume_checkpoint(
                            run_id=run_id,
                            checkpoint=checkpoint,
                        )
                        yield self._create_codex_user_input_pause_event(
                            run_id=run_id,
                            request=server_request,
                        )
                        return

                    await rpc.respond(
                        server_request.raw_id,
                        error={
                            "code": -32601,
                            "message": f"Unsupported server request: {server_request.method}",
                        },
                    )
                    continue

                notification = payload
                if not isinstance(notification, dict):
                    continue

                method = str(notification.get("method") or "")
                params = notification.get("params")
                params_dict = params if isinstance(params, dict) else {}

                if method in {"thread/tokenUsage/updated", "serverRequest/resolved"}:
                    continue

                if method == "error":
                    message = _extract_text(params_dict) or "Codex app-server failed."
                    last_error_message = message
                    continue

                if _is_agent_message_delta(method):
                    delta_text = _extract_text(params_dict)
                    if delta_text:
                        content_parts.append(delta_text)
                        yield RunContentDeltaEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            content=delta_text,
                        )
                    continue

                if _is_reasoning_method(method) and method.endswith("/delta"):
                    reasoning_delta = _extract_text(params_dict)
                    if reasoning_delta:
                        yield ReasoningDeltaEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            reasoning_content=reasoning_delta,
                        )
                    continue

                if method == "item/completed":
                    item = params_dict.get("item")
                    if isinstance(item, dict) and item.get("type") == "agentMessage":
                        text = item.get("text")
                        if isinstance(text, str) and text and not content_parts:
                            content_parts.append(text)
                    continue

                if method == "turn/completed":
                    turn = params_dict.get("turn")
                    turn_dict = turn if isinstance(turn, dict) else {}
                    status = str(turn_dict.get("status") or "")
                    error = turn_dict.get("error")
                    error_message = (
                        _extract_text(error) or last_error_message or "Codex turn failed."
                    )
                    final_content = "".join(content_parts)

                    if status == "completed":
                        yield RunCompletedEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            content=final_content,
                        )
                        return

                    if status == "interrupted":
                        yield RunCancelledEvent(
                            agent_id=self.id or "",
                            agent_name=self.name,
                            run_id=run_id,
                            session_id=self.session_id,
                            model=self.llm_config.model,
                            model_provider=self.llm_config.provider,
                            reason="Run was cancelled",
                        )
                        return

                    yield RunErrorEvent(
                        agent_id=self.id or "",
                        agent_name=self.name,
                        run_id=run_id,
                        session_id=self.session_id,
                        model=self.llm_config.model,
                        model_provider=self.llm_config.provider,
                        content=error_message,
                    )
                    return

        except RunCancelledException:
            yield RunCancelledEvent(
                agent_id=self.id or "",
                agent_name=self.name,
                run_id=run_id,
                session_id=self.session_id,
                model=self.llm_config.model,
                model_provider=self.llm_config.provider,
                reason="Run was cancelled",
            )
        except Exception as exc:
            logger.error(f"Codex runtime continue_run {run_id} failed: {exc}", exc_info=True)
            diagnostics = rpc.debug_output() if rpc is not None else ""
            message = str(exc)
            if diagnostics:
                message = f"{message}\n{diagnostics}"
            yield RunErrorEvent(
                agent_id=self.id or "",
                agent_name=self.name,
                run_id=run_id,
                session_id=self.session_id,
                model=self.llm_config.model,
                model_provider=self.llm_config.provider,
                content=message,
            )
        finally:
            await cleanup_run(run_id)
            if handle is not None:
                try:
                    await handle.kill()
                except Exception:
                    logger.debug("Failed to kill Codex app-server PTY", exc_info=True)
                try:
                    await handle.disconnect()
                except Exception:
                    logger.debug("Failed to disconnect Codex app-server PTY", exc_info=True)

    async def _ensure_sandbox(self) -> Sandbox:
        if self.sandbox is not None:
            return self.sandbox

        container = get_app_container()
        async with get_db_session_local() as db:
            sandbox = await container.sandbox_service.init_sandbox(
                db,
                session_id=UUID(self.session_id),
                user_id=UUID(self.user_id),
            )
        self.sandbox = sandbox
        return sandbox

    async def _start_app_server(
        self, sandbox: Sandbox, *, run_id: str
    ) -> tuple[LiveTerminalHandle, _CodexAppServerSession]:
        rpc_holder: dict[str, _CodexAppServerSession] = {}
        log_mirror = _CodexPtyLogMirror(session_id=self.session_id, run_id=run_id)
        loop = asyncio.get_running_loop()

        def on_data(data: bytes) -> None:
            loop.call_soon_threadsafe(log_mirror.feed_data, data)
            rpc = rpc_holder.get("rpc")
            if rpc is not None:
                loop.call_soon_threadsafe(rpc.feed_data, data)

        handle = await sandbox.create_live_terminal(
            cols=120,
            rows=40,
            cwd=_WORKSPACE_CWD,
            envs=_TERMINAL_ENVS,
            on_data=on_data,
            timeout=0,
        )
        rpc = _CodexAppServerSession(handle=handle)
        rpc_holder["rpc"] = rpc

        await handle.send_input(_app_server_bootstrap_command().encode())

        await asyncio.sleep(0.1)
        await rpc.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ii_agent",
                    "title": "II Agent",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await rpc.notify("initialized", {})
        return handle, rpc

    async def _load_thread_binding(self) -> _CodexBinding | None:
        container = get_app_container()
        async with get_db_session_local() as db:
            session = await container.session_service.get_session_by_id(db, UUID(self.session_id))
        return _CodexBinding.from_session_metadata(
            getattr(session, "session_metadata", None) if session is not None else None
        )

    async def _persist_thread_binding(self, binding: _CodexBinding) -> None:
        container = get_app_container()
        async with get_db_session_local() as db:
            session = await container.session_service.get_session_by_id(db, UUID(self.session_id))
            session_metadata = getattr(session, "session_metadata", None) if session else None
            await container.session_service.update_session_fields(
                db,
                UUID(self.session_id),
                session_metadata=binding.into_session_metadata(session_metadata),
            )
            await db.commit()

    async def _start_or_resume_thread(
        self,
        *,
        rpc: _CodexAppServerSession,
        binding: _CodexBinding | None,
    ) -> tuple[str, _CodexBinding]:
        tool_fingerprint = self._dynamic_tool_fingerprint()
        should_resume = (
            binding is not None
            and binding.model == self.llm_config.model
            and binding.dynamic_tool_fingerprint == tool_fingerprint
        )
        if should_resume:
            try:
                result = await rpc.request(
                    "thread/resume",
                    {
                        "threadId": binding.thread_id,
                        "cwd": _WORKSPACE_CWD,
                        "approvalPolicy": _THREAD_APPROVAL_POLICY,
                        "sandbox": _THREAD_SANDBOX,
                        "personality": "pragmatic",
                        "model": self.llm_config.model,
                    },
                )
                thread = result.get("thread")
                if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                    resumed = _CodexBinding(
                        thread_id=thread["id"],
                        model=self.llm_config.model,
                        last_turn_id=binding.last_turn_id,
                        dynamic_tool_fingerprint=tool_fingerprint,
                    )
                    await self._persist_thread_binding(resumed)
                    return thread["id"], resumed
            except Exception:
                logger.info(
                    f"Codex thread resume failed for session {self.session_id}; starting a fresh thread",
                    exc_info=True,
                )

        start_params = {
            "cwd": _WORKSPACE_CWD,
            "approvalPolicy": _THREAD_APPROVAL_POLICY,
            "sandbox": _THREAD_SANDBOX,
            "personality": "pragmatic",
            "model": self.llm_config.model,
            "serviceName": "ii_agent",
            "sessionStartSource": "startup",
        }
        dynamic_tools = self._dynamic_tool_specs()
        if dynamic_tools:
            start_params["dynamicTools"] = dynamic_tools

        result = await rpc.request("thread/start", start_params)
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise RuntimeError("Codex app-server returned an invalid thread/start response.")

        created = _CodexBinding(
            thread_id=thread["id"],
            model=self.llm_config.model,
            dynamic_tool_fingerprint=tool_fingerprint,
        )
        await self._persist_thread_binding(created)
        return thread["id"], created

    async def _resume_thread(self, *, rpc: _CodexAppServerSession, thread_id: str) -> None:
        await rpc.request(
            "thread/resume",
            {
                "threadId": thread_id,
                "cwd": _WORKSPACE_CWD,
                "approvalPolicy": _THREAD_APPROVAL_POLICY,
                "sandbox": _THREAD_SANDBOX,
                "personality": "pragmatic",
                "model": self.llm_config.model,
            },
        )

    def _build_prompt_text(
        self,
        *,
        input: str | list | dict | Message | BaseModel | list[Message],
        files: Sequence[File] | None,
    ) -> str:
        prompt_text = _stringify_input(input)
        sandbox_files = [
            str(file.filepath) for file in files or [] if getattr(file, "filepath", None)
        ]
        if not sandbox_files:
            return prompt_text

        attachment_block = "\n".join(f"- {path}" for path in sandbox_files)
        if prompt_text:
            return f"{prompt_text}\n\nAttached sandbox files are available at:\n{attachment_block}"
        return f"Attached sandbox files are available at:\n{attachment_block}"

    def _build_turn_params(
        self,
        *,
        thread_id: str,
        prompt_text: str,
        images: Sequence[Image] | None,
    ) -> dict[str, Any]:
        input_items: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]

        for image in images or []:
            if getattr(image, "filepath", None):
                input_items.append({"type": "localImage", "path": str(image.filepath)})
            elif getattr(image, "url", None):
                input_items.append({"type": "image", "url": str(image.url)})

        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": input_items,
            "cwd": _WORKSPACE_CWD,
            "approvalPolicy": _THREAD_APPROVAL_POLICY,
            "sandboxPolicy": {
                "type": "workspaceWrite",
                "writableRoots": [_WORKSPACE_CWD],
                "networkAccess": True,
            },
            "model": self.llm_config.model,
            "personality": "pragmatic",
        }
        if self.system_message:
            params["settings"] = {"developer_instructions": self.system_message}
        return params

    def _dynamic_tool_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for tool in self._tools.values():
            tool_name = getattr(tool, "name", None)
            if not isinstance(tool_name, str) or not tool_name:
                continue
            description = getattr(tool, "description", "") or ""
            input_schema = getattr(tool, "input_schema", None)
            specs.append(
                {
                    "name": tool_name,
                    "description": str(description),
                    "inputSchema": input_schema if isinstance(input_schema, dict) else {},
                }
            )
        return specs

    def _dynamic_tool_fingerprint(self) -> str | None:
        specs = self._dynamic_tool_specs()
        if not specs:
            return None
        payload = json.dumps(specs, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _execute_dynamic_tool_call(
        self, *, request: _CodexServerRequest
    ) -> _DynamicToolCallOutcome:
        tool_name = self._extract_dynamic_tool_name(request.params)
        arguments = self._extract_dynamic_tool_arguments(request.params)

        if not tool_name or tool_name not in self._tools:
            return _DynamicToolCallOutcome(
                response=self._dynamic_tool_text_response(
                    f"Unsupported dynamic tool call: {tool_name or 'unknown tool'}",
                    success=False,
                )
            )

        tool = self._tools[tool_name]
        try:
            result = await tool.execute(arguments)
        except Exception as exc:
            logger.error("Codex dynamic tool %s failed: %s", tool_name, exc, exc_info=True)
            return _DynamicToolCallOutcome(
                response=self._dynamic_tool_text_response(
                    f"Dynamic tool {tool_name} failed: {exc}",
                    success=False,
                )
            )

        if not isinstance(result, ToolResult):
            return _DynamicToolCallOutcome(
                response=self._dynamic_tool_text_response(str(result), success=True)
            )

        response = self._dynamic_tool_response_from_result(result)
        content = self._tool_result_text(result)
        should_stop = bool(getattr(tool, "stop_after_tool_call", False) or result.is_interrupted)
        return _DynamicToolCallOutcome(
            response=response,
            should_stop=should_stop,
            content=content,
        )

    @staticmethod
    def _extract_dynamic_tool_name(params: dict[str, Any]) -> str | None:
        for key in ("tool", "name"):
            value = params.get(key)
            if isinstance(value, str) and value:
                return value
        item = params.get("item")
        if isinstance(item, dict):
            return CodexRuntimeAgent._extract_dynamic_tool_name(item)
        return None

    @staticmethod
    def _extract_dynamic_tool_arguments(params: dict[str, Any]) -> dict[str, Any]:
        arguments = params.get("arguments")
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        item = params.get("item")
        if isinstance(item, dict):
            return CodexRuntimeAgent._extract_dynamic_tool_arguments(item)
        return {}

    @staticmethod
    def _dynamic_tool_response_from_result(result: ToolResult) -> dict[str, Any]:
        llm_content = result.llm_content
        content_items: list[dict[str, Any]] = []
        if isinstance(llm_content, str):
            content_items.append({"type": "inputText", "text": llm_content})
        elif isinstance(llm_content, list):
            for item in llm_content:
                if isinstance(item, TextContent):
                    content_items.append({"type": "inputText", "text": item.text})
                elif isinstance(item, ImageContent):
                    image_url = item.data
                    if not image_url.startswith("data:"):
                        image_url = f"data:{item.mime_type};base64,{item.data}"
                    content_items.append({"type": "inputImage", "imageUrl": image_url})
                else:
                    content_items.append({"type": "inputText", "text": str(item)})
        else:
            content_items.append({"type": "inputText", "text": str(llm_content)})

        if not content_items:
            content_items.append({"type": "inputText", "text": ""})
        return {
            "contentItems": content_items,
            "success": not bool(result.is_error),
        }

    @staticmethod
    def _dynamic_tool_text_response(text: str, *, success: bool) -> dict[str, Any]:
        return {
            "contentItems": [{"type": "inputText", "text": text}],
            "success": success,
        }

    @staticmethod
    def _tool_result_text(result: ToolResult) -> str:
        llm_content = result.llm_content
        if isinstance(llm_content, str):
            return llm_content
        if isinstance(llm_content, list):
            parts: list[str] = []
            for item in llm_content:
                if isinstance(item, TextContent):
                    parts.append(item.text)
                elif isinstance(item, ImageContent):
                    parts.append("[image]")
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(llm_content)

    async def _persist_codex_resume_checkpoint(
        self,
        *,
        run_id: str,
        checkpoint: CodexResumeCheckpoint,
    ) -> None:
        container = get_app_container()
        async with get_db_session_local() as db:
            await container.run_checkpoint_service.write_codex_resume_checkpoint(
                db,
                task_id=UUID(run_id),
                checkpoint=checkpoint,
            )
            await db.commit()

    @staticmethod
    def _build_approval_checkpoint(
        *,
        request: _CodexServerRequest,
        fallback_thread_id: str,
        fallback_turn_id: str | None,
    ) -> CodexResumeCheckpoint:
        thread_id = request.params.get("threadId")
        turn_id = request.params.get("turnId")
        available_decisions = request.params.get("availableDecisions")
        return CodexResumeCheckpoint(
            thread_id=thread_id if isinstance(thread_id, str) else fallback_thread_id,
            turn_id=turn_id if isinstance(turn_id, str) else (fallback_turn_id or ""),
            pending_request_id=request.request_id,
            pending_request_kind="approval",
            request_payload={"method": request.method, **request.params},
            allowed_decisions=CodexRuntimeAgent._normalise_decision_names(available_decisions),
            pause_reason="approval",
        )

    def _build_user_input_checkpoint(
        self,
        *,
        request: _CodexServerRequest,
        fallback_thread_id: str,
        fallback_turn_id: str | None,
    ) -> CodexResumeCheckpoint:
        thread_id = request.params.get("threadId")
        turn_id = request.params.get("turnId")
        return CodexResumeCheckpoint(
            thread_id=thread_id if isinstance(thread_id, str) else fallback_thread_id,
            turn_id=turn_id if isinstance(turn_id, str) else (fallback_turn_id or ""),
            pending_request_id=request.request_id,
            pending_request_kind="user_input",
            request_payload={"method": request.method, **request.params},
            registered_tool_fingerprint=self._dynamic_tool_fingerprint(),
            pause_reason="user_input",
        )

    def _create_codex_approval_pause_event(
        self,
        *,
        run_id: str,
        request: _CodexServerRequest,
    ) -> RunPausedEvent:
        tool = ToolExecution(
            tool_call_id=request.request_id,
            tool_name=self._approval_tool_name(request.method),
            tool_args={"request_method": request.method, **request.params},
            requires_confirmation=True,
        )
        requirement = RunRequirement(tool)
        return RunPausedEvent(
            agent_id=self.id or "",
            agent_name=self.name,
            run_id=run_id,
            session_id=self.session_id,
            model=self.llm_config.model,
            model_provider=self.llm_config.provider,
            content="Codex is awaiting approval",
            tools=[tool],
            requirements=[requirement],
        )

    def _create_codex_user_input_pause_event(
        self,
        *,
        run_id: str,
        request: _CodexServerRequest,
    ) -> RunPausedEvent:
        tool = ToolExecution(
            tool_call_id=request.request_id,
            tool_name=self._user_input_tool_name(request.method),
            tool_args={"request_method": request.method, **request.params},
            requires_user_input=True,
            user_input_schema=self._user_input_schema_for_request(request),
        )
        requirement = RunRequirement(tool)
        return RunPausedEvent(
            agent_id=self.id or "",
            agent_name=self.name,
            run_id=run_id,
            session_id=self.session_id,
            model=self.llm_config.model,
            model_provider=self.llm_config.provider,
            content="Codex is awaiting user input",
            tools=[tool],
            requirements=[requirement],
        )

    @staticmethod
    def _approval_tool_name(method: str) -> str:
        if method == "item/commandExecution/requestApproval":
            return "codex_command_execution_approval"
        if method == "item/fileChange/requestApproval":
            return "codex_file_change_approval"
        if method == "item/permissions/requestApproval":
            return "codex_permissions_approval"
        return "codex_approval"

    @staticmethod
    def _user_input_tool_name(method: str) -> str:
        if method == "mcpServer/elicitation/request":
            return "codex_mcp_elicitation"
        return "codex_request_user_input"

    @staticmethod
    def _user_input_schema_for_request(request: _CodexServerRequest) -> list[UserInputField]:
        if request.method == "item/tool/requestUserInput":
            fields: list[UserInputField] = []
            questions = request.params.get("questions")
            if isinstance(questions, list):
                for question in questions:
                    if not isinstance(question, dict):
                        continue
                    question_id = question.get("id")
                    if not isinstance(question_id, str) or not question_id:
                        continue
                    description = question.get("question") or question.get("header")
                    fields.append(
                        UserInputField(
                            name=question_id,
                            field_type=str,
                            description=description if isinstance(description, str) else None,
                        )
                    )
            if fields:
                return fields

        if request.method == "mcpServer/elicitation/request":
            requested_schema = request.params.get("requestedSchema")
            if isinstance(requested_schema, dict):
                properties = requested_schema.get("properties")
                if isinstance(properties, dict):
                    fields = []
                    for name, schema in properties.items():
                        if not isinstance(name, str):
                            continue
                        field_type = str
                        description = None
                        if isinstance(schema, dict):
                            field_type = CodexRuntimeAgent._python_type_for_json_schema(
                                schema.get("type")
                            )
                            raw_description = schema.get("description")
                            description = (
                                raw_description if isinstance(raw_description, str) else None
                            )
                        fields.append(
                            UserInputField(
                                name=name,
                                field_type=field_type,
                                description=description,
                            )
                        )
                    if fields:
                        return fields

        prompt = request.params.get("prompt") or request.params.get("message")
        return [
            UserInputField(
                name="response",
                field_type=str,
                description=prompt if isinstance(prompt, str) else None,
            )
        ]

    @staticmethod
    def _python_type_for_json_schema(schema_type: Any) -> type:
        if schema_type == "boolean":
            return bool
        if schema_type == "integer":
            return int
        if schema_type == "number":
            return float
        return str

    @staticmethod
    def _matches_resume_checkpoint(
        *,
        request: _CodexServerRequest,
        checkpoint: CodexResumeCheckpoint,
    ) -> bool:
        if checkpoint.pending_request_kind == "approval":
            if not _is_approval_request(request.method):
                return False
        elif checkpoint.pending_request_kind == "user_input":
            if not _is_user_input_request(request.method):
                return False
        else:
            return False

        request_method = checkpoint.request_payload.get("method")
        if isinstance(request_method, str) and request.method != request_method:
            return False
        request_thread_id = request.params.get("threadId")
        if isinstance(request_thread_id, str) and request_thread_id != checkpoint.thread_id:
            return False
        request_turn_id = request.params.get("turnId")
        if isinstance(request_turn_id, str) and request_turn_id != checkpoint.turn_id:
            return False
        item_id = request.params.get("itemId")
        checkpoint_item_id = checkpoint.request_payload.get("itemId")
        if isinstance(item_id, str) and isinstance(checkpoint_item_id, str):
            return item_id == checkpoint_item_id
        call_id = request.params.get("callId")
        checkpoint_call_id = checkpoint.request_payload.get("callId")
        if isinstance(call_id, str) and isinstance(checkpoint_call_id, str):
            return call_id == checkpoint_call_id
        elicitation_id = request.params.get("elicitationId")
        checkpoint_elicitation_id = checkpoint.request_payload.get("elicitationId")
        if isinstance(elicitation_id, str) and isinstance(checkpoint_elicitation_id, str):
            return elicitation_id == checkpoint_elicitation_id
        return True

    @staticmethod
    def _resume_result_for_checkpoint(
        *,
        request: _CodexServerRequest,
        checkpoint: CodexResumeCheckpoint,
        decision: str,
        policy_patch: dict[str, Any] | None,
        user_input: dict[str, Any],
    ) -> Any:
        if checkpoint.pending_request_kind == "approval":
            if request.method == "item/permissions/requestApproval":
                return CodexRuntimeAgent._permissions_approval_result_for_decision(
                    request=request,
                    decision=decision,
                )
            return CodexRuntimeAgent._approval_result_for_decision(
                request_method=request.method,
                decision=decision,
                policy_patch=policy_patch,
                allowed_decisions=checkpoint.allowed_decisions,
            )
        if request.method == "mcpServer/elicitation/request":
            return CodexRuntimeAgent._mcp_elicitation_result_for_decision(
                decision=decision,
                user_input=user_input,
            )
        return CodexRuntimeAgent._tool_user_input_result_for_decision(
            request=request,
            decision=decision,
            user_input=user_input,
        )

    @staticmethod
    def _approval_result_for_decision(
        *,
        request_method: str,
        decision: str,
        policy_patch: dict[str, Any] | None,
        allowed_decisions: list[str] | None = None,
    ) -> Any:
        allowed = {candidate for candidate in allowed_decisions or [] if isinstance(candidate, str)}

        if decision == "approve_once":
            execpolicy_amendment = (
                policy_patch.get("execpolicy_amendment") if isinstance(policy_patch, dict) else None
            )
            if not execpolicy_amendment and isinstance(policy_patch, dict):
                execpolicy_amendment = policy_patch.get("execpolicyAmendment")
            can_amend_execpolicy = request_method == "item/commandExecution/requestApproval" and (
                not allowed or "acceptWithExecpolicyAmendment" in allowed
            )
            if execpolicy_amendment and can_amend_execpolicy:
                return {
                    "decision": {
                        "acceptWithExecpolicyAmendment": {
                            "execpolicyAmendment": execpolicy_amendment,
                        }
                    }
                }
            if allowed and "accept" not in allowed and "acceptForSession" in allowed:
                return {"decision": "acceptForSession"}
            return {"decision": "accept"}
        if decision == "approve_session":
            if allowed and "acceptForSession" not in allowed and "accept" in allowed:
                return {"decision": "accept"}
            return {"decision": "acceptForSession"}
        if decision == "cancel":
            return {"decision": "cancel"}
        return {"decision": "decline"}

    @staticmethod
    def _permissions_approval_result_for_decision(
        *,
        request: _CodexServerRequest,
        decision: str,
    ) -> dict[str, Any]:
        if decision not in {"approve_once", "approve_session"}:
            return {"permissions": {}}
        permissions = request.params.get("permissions")
        return {
            "permissions": permissions if isinstance(permissions, dict) else {},
            "scope": "session" if decision == "approve_session" else "turn",
        }

    @staticmethod
    def _normalise_decision_names(raw_decisions: Any) -> list[str]:
        if not isinstance(raw_decisions, list):
            return []
        names: list[str] = []
        for raw_decision in raw_decisions:
            if isinstance(raw_decision, str):
                names.append(raw_decision)
            elif isinstance(raw_decision, dict):
                names.extend(key for key in raw_decision if isinstance(key, str))
        return names

    @staticmethod
    def _tool_user_input_result_for_decision(
        *,
        request: _CodexServerRequest,
        decision: str,
        user_input: dict[str, Any],
    ) -> dict[str, Any]:
        if decision in {"reject", "cancel"}:
            return {"answers": {}}

        answers: dict[str, dict[str, list[str]]] = {}
        question_ids = CodexRuntimeAgent._question_ids_for_request(request)
        if not question_ids:
            question_ids = [key for key in user_input if isinstance(key, str)]

        for question_id in question_ids:
            if question_id not in user_input:
                continue
            raw_answer = user_input[question_id]
            if isinstance(raw_answer, list):
                values = [str(value) for value in raw_answer]
            else:
                values = [str(raw_answer)]
            answers[question_id] = {"answers": values}

        return {"answers": answers}

    @staticmethod
    def _question_ids_for_request(request: _CodexServerRequest) -> list[str]:
        questions = request.params.get("questions")
        if not isinstance(questions, list):
            return []
        question_ids: list[str] = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            question_id = question.get("id")
            if isinstance(question_id, str) and question_id:
                question_ids.append(question_id)
        return question_ids

    @staticmethod
    def _mcp_elicitation_result_for_decision(
        *,
        decision: str,
        user_input: dict[str, Any],
    ) -> dict[str, Any]:
        if decision == "cancel":
            return {"action": "cancel", "content": None}
        if decision == "reject":
            return {"action": "decline", "content": None}
        return {"action": "accept", "content": user_input or {}}
