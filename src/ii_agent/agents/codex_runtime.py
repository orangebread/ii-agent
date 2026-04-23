from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel

from ii_agent.agents.models.message import Message
from ii_agent.agents.runs.agent import (
    ReasoningDeltaEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentDeltaEvent,
    RunErrorEvent,
    RunStartedEvent,
)
from ii_agent.agents.sandboxes import Sandbox
from ii_agent.agents.sandboxes.terminal import LiveTerminalHandle
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


_CODEX_METADATA_KEY = "codex_runtime"
_WORKSPACE_CWD = "/workspace"
_TERMINAL_ENVS = {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
}
_REQUEST_TIMEOUT_SECONDS = 30.0
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


@dataclass
class _CodexBinding:
    thread_id: str
    model: str | None = None
    last_turn_id: str | None = None

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
        return cls(
            thread_id=thread_id,
            model=model if isinstance(model, str) else None,
            last_turn_id=last_turn_id if isinstance(last_turn_id, str) else None,
        )

    def into_session_metadata(self, session_metadata: dict[str, Any] | None) -> dict[str, Any]:
        updated_metadata = dict(session_metadata or {})
        updated_metadata[_CODEX_METADATA_KEY] = {
            "thread_id": self.thread_id,
            "model": self.model,
            "last_turn_id": self.last_turn_id,
        }
        return updated_metadata


class _CodexRpcError(RuntimeError):
    """Raised when the Codex app-server rejects a JSON-RPC request."""


class _CodexAppServerSession:
    """Minimal JSON-RPC client over a sandbox PTY."""

    def __init__(self, *, handle: LiveTerminalHandle) -> None:
        self._handle = handle
        self._loop = asyncio.get_running_loop()
        self._buffer = ""
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._pending_methods: dict[int, str] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
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
            request_id = int(payload["id"])
            future = self._pending.pop(request_id, None)
            self._pending_methods.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(payload)
            return

        if "method" in payload and "id" in payload:
            request_id = int(payload["id"])
            method = str(payload.get("method") or "")
            if self._pending_methods.get(request_id) == method:
                return
            self._loop.create_task(self._handle_server_request(payload))
            return

        if "method" in payload:
            self._notifications.put_nowait(payload)
            return

        self._raw_lines.append(json.dumps(payload))

    async def _handle_server_request(self, payload: dict[str, Any]) -> None:
        method = str(payload.get("method") or "")
        request_id = payload.get("id")

        if method.endswith("requestApproval"):
            await self._send(
                {
                    "id": request_id,
                    "result": {"decision": "cancel"},
                }
            )
            return

        if method == "item/tool/call":
            await self._send(
                {
                    "id": request_id,
                    "result": {
                        "contentItems": [
                            {
                                "type": "inputText",
                                "text": (
                                    "Dynamic tool calls are not supported by this ii-agent "
                                    "Codex transport yet."
                                ),
                            }
                        ],
                        "success": False,
                    },
                }
            )
            return

        if method.endswith("requestUserInput") or method == "mcpServer/elicitation/request":
            await self._send(
                {
                    "id": request_id,
                    "result": {"action": "cancel", "content": None},
                }
            )
            return

        await self._send(
            {
                "id": request_id,
                "error": {"code": -32601, "message": f"Unsupported server request: {method}"},
            }
        )

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

    async def next_notification(self, *, timeout: float = 0.25) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._notifications.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

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

    def set_id(self) -> None:
        if self.id is None:
            self.id = f"{self.name}-{self.session_id}"

    def add_tool(self, tool: Any) -> None:
        raise RuntimeError(
            "Codex runtime sessions do not support agent-managed tool injection yet."
        )

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise RuntimeError("Codex runtime sessions do not support continue_run yet.")

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

                notification = await rpc.next_notification()
                if notification is None:
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
                }
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
        should_resume = binding is not None and binding.model == self.llm_config.model
        if should_resume:
            try:
                result = await rpc.request(
                    "thread/resume",
                    {
                        "threadId": binding.thread_id,
                        "cwd": _WORKSPACE_CWD,
                        "approvalPolicy": "never",
                        "sandbox": "workspace-write",
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
                    )
                    await self._persist_thread_binding(resumed)
                    return thread["id"], resumed
            except Exception:
                logger.info(
                    f"Codex thread resume failed for session {self.session_id}; starting a fresh thread",
                    exc_info=True,
                )

        result = await rpc.request(
            "thread/start",
            {
                "cwd": _WORKSPACE_CWD,
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
                "personality": "pragmatic",
                "model": self.llm_config.model,
                "serviceName": "ii_agent",
                "sessionStartSource": "startup",
            },
        )
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise RuntimeError("Codex app-server returned an invalid thread/start response.")

        created = _CodexBinding(thread_id=thread["id"], model=self.llm_config.model)
        await self._persist_thread_binding(created)
        return thread["id"], created

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
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "model": self.llm_config.model,
            "personality": "pragmatic",
        }
        if self.system_message:
            params["settings"] = {"developer_instructions": self.system_message}
        return params
