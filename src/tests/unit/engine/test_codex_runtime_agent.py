from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ii_agent.agents.codex_runtime import (
    CodexRuntimeAgent,
    _CodexAppServerSession,
    _CodexPtyLogMirror,
    _CodexServerRequest,
    _app_server_bootstrap_command,
    _normalize_pty_log_line,
)
from ii_agent.agents.runs.agent import (
    RunCompletedEvent,
    RunErrorEvent,
    RunPausedEvent,
    RunStartedEvent,
)
from ii_agent.agents.tools.base import ToolResult
from ii_agent.core.config.llm_config import LLMConfig
from ii_agent.files import File, Image
from ii_agent.settings.llm import Provider
from ii_agent.tasks.schemas import CodexResumeCheckpoint


pytestmark = pytest.mark.unit


class _FakeHandle:
    def __init__(self) -> None:
        self.send_input = AsyncMock()


@pytest.mark.asyncio
async def test_agent_factory_routes_codex_runtime_to_custom_agent(monkeypatch):
    from ii_agent.agents.factory.agent import AgentFactory
    from ii_agent.agents.factory.tools import AgentType
    from ii_agent.agents.tools.skill import SkillTool

    captured: dict[str, object] = {}

    class FakeCodexRuntimeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_id(self) -> None:
            captured["set_id_called"] = True

    class FakeSkillCreator:
        async def create_skill_tool(self):
            return SkillTool(
                description=(
                    "<skills_instructions>\n"
                    "Use skills when helpful.\n"
                    "</skills_instructions>\n\n"
                    "<available_skills>\n"
                    "<skill>\n"
                    "<name>demo-skill</name>\n"
                    "<description>Demo description</description>\n"
                    "</skill>\n"
                    "</available_skills>"
                ),
                skills_registry={},
            )

    async def fake_system_prompt(**kwargs) -> str:
        return "BASE PROMPT"

    def unexpected_tool_resolution(**kwargs):
        raise AssertionError("Codex runtime should bypass agent tool resolution")

    monkeypatch.setattr(
        "ii_agent.agents.factory.agent.AgentToolManager.resolve_tools",
        unexpected_tool_resolution,
    )
    monkeypatch.setattr(
        "ii_agent.agents.factory.agent.get_system_prompt_for_agent_type",
        fake_system_prompt,
    )
    monkeypatch.setattr(
        "ii_agent.agents.factory.agent.CodexRuntimeAgent",
        FakeCodexRuntimeAgent,
    )

    factory = AgentFactory(config=SimpleNamespace())
    llm_config = LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex")

    await factory.create_agent(
        user_id="user-1",
        session_id="session-1",
        llm_config=llm_config,
        agent_type=AgentType.CODEX,
        skill_creator=FakeSkillCreator(),
    )

    assert captured["set_id_called"] is True
    assert captured["llm_config"] == llm_config
    assert captured["name"] == "codex_agent"
    assert "<available_skills>" in captured["system_message"]
    assert captured["system_message"].startswith("BASE PROMPT")


def test_codex_runtime_builds_turn_input_from_files_and_images():
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )

    prompt_text = agent._build_prompt_text(
        input="Inspect the attachments.",
        files=[File(filepath="/workspace/notes.txt", mime_type="text/plain", filename="notes.txt")],
    )
    params = agent._build_turn_params(
        thread_id="thr_123",
        prompt_text=prompt_text,
        images=[Image(filepath="/workspace/screenshot.png")],
    )

    assert "Attached sandbox files are available at" in prompt_text
    assert params["settings"] == {"developer_instructions": "Follow repo instructions."}
    assert params["approvalPolicy"] == "untrusted"
    assert params["sandboxPolicy"] == {
        "type": "workspaceWrite",
        "writableRoots": ["/workspace"],
        "networkAccess": True,
    }
    assert params["input"][0]["type"] == "text"
    assert params["input"][1] == {"type": "localImage", "path": "/workspace/screenshot.png"}


def test_codex_approval_result_only_uses_execpolicy_for_command_approval():
    assert CodexRuntimeAgent._approval_result_for_decision(
        request_method="item/commandExecution/requestApproval",
        decision="approve_once",
        policy_patch={"execpolicy_amendment": {"program": "pytest"}},
        allowed_decisions=["accept", "acceptWithExecpolicyAmendment", "decline"],
    ) == {
        "decision": {
            "acceptWithExecpolicyAmendment": {
                "execpolicyAmendment": {"program": "pytest"},
            }
        }
    }

    assert CodexRuntimeAgent._approval_result_for_decision(
        request_method="item/fileChange/requestApproval",
        decision="approve_once",
        policy_patch={"execpolicy_amendment": {"program": "pytest"}},
        allowed_decisions=["accept", "acceptForSession", "decline"],
    ) == {"decision": "accept"}


def test_codex_normalises_object_shaped_allowed_decisions():
    assert CodexRuntimeAgent._normalise_decision_names(
        [
            "accept",
            {"acceptWithExecpolicyAmendment": {"execpolicyAmendment": {"program": "pytest"}}},
            "decline",
        ]
    ) == ["accept", "acceptWithExecpolicyAmendment", "decline"]


def test_codex_permissions_approval_returns_permission_profile_response():
    request = _CodexServerRequest(
        raw_id="req_permissions",
        method="item/permissions/requestApproval",
        params={
            "permissions": {
                "network": {"enabled": True},
                "fileSystem": {"read": ["/workspace"], "write": ["/workspace/app"]},
            }
        },
    )

    assert CodexRuntimeAgent._permissions_approval_result_for_decision(
        request=request,
        decision="approve_session",
    ) == {
        "permissions": {
            "network": {"enabled": True},
            "fileSystem": {"read": ["/workspace"], "write": ["/workspace/app"]},
        },
        "scope": "session",
    }
    assert CodexRuntimeAgent._permissions_approval_result_for_decision(
        request=request,
        decision="reject",
    ) == {"permissions": {}}


@pytest.mark.asyncio
async def test_codex_runtime_starts_thread_with_workspace_write_contract(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    captured: list[tuple[str, dict]] = []

    class FakeRpc:
        async def request(self, method: str, params: dict) -> dict:
            captured.append((method, params))
            return {"thread": {"id": "thr_123"}}

    monkeypatch.setattr(agent, "_persist_thread_binding", AsyncMock())

    thread_id, binding = await agent._start_or_resume_thread(
        rpc=FakeRpc(),
        binding=None,
    )

    assert thread_id == "thr_123"
    assert binding.thread_id == "thr_123"
    assert captured == [
        (
            "thread/start",
            {
                "cwd": "/workspace",
                "approvalPolicy": "untrusted",
                "sandbox": "workspace-write",
                "personality": "pragmatic",
                "model": "gpt-5.4",
                "serviceName": "ii_agent",
                "sessionStartSource": "startup",
            },
        )
    ]


@pytest.mark.asyncio
async def test_codex_runtime_registers_dynamic_tools_on_fresh_thread(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )

    class FakeTool:
        name = "submit_plan"
        description = "Submit a plan"
        input_schema = {"type": "object", "properties": {"summary": {"type": "string"}}}

    agent.add_tool(FakeTool())
    captured: list[tuple[str, dict]] = []

    class FakeRpc:
        async def request(self, method: str, params: dict) -> dict:
            captured.append((method, params))
            return {"thread": {"id": "thr_123"}}

    monkeypatch.setattr(agent, "_persist_thread_binding", AsyncMock())

    _thread_id, binding = await agent._start_or_resume_thread(
        rpc=FakeRpc(),
        binding=None,
    )

    assert captured[0][0] == "thread/start"
    assert captured[0][1]["dynamicTools"] == [
        {
            "name": "submit_plan",
            "description": "Submit a plan",
            "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}}},
        }
    ]
    assert binding.dynamic_tool_fingerprint is not None


@pytest.mark.asyncio
async def test_codex_runtime_reports_sandbox_startup_failure_as_run_error(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )

    async def _raise_sandbox_error():
        raise RuntimeError("sandbox bootstrap failed")

    monkeypatch.setattr(agent, "_ensure_sandbox", _raise_sandbox_error)

    events = [
        event
        async for event in agent._arun_stream(
            input="Run Codex",
            run_id=str(uuid.uuid4()),
            images=None,
            files=None,
        )
    ]

    assert len(events) == 1
    assert isinstance(events[0], RunErrorEvent)
    assert events[0].content == "sandbox bootstrap failed"


@pytest.mark.asyncio
async def test_codex_runtime_initializes_app_server_with_experimental_api(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    captured: dict[str, object] = {}
    handle = MagicMock()
    handle.send_input = AsyncMock()
    sandbox = MagicMock()
    sandbox.create_live_terminal = AsyncMock(return_value=handle)

    class FakeRpcSession:
        def __init__(self, *, handle):
            captured["handle"] = handle

        def feed_data(self, data: bytes) -> None:
            return None

        async def request(self, method: str, params: dict) -> dict:
            captured["request"] = (method, params)
            return {}

        async def notify(self, method: str, params: dict) -> None:
            captured["notify"] = (method, params)

    monkeypatch.setattr("ii_agent.agents.codex_runtime._CodexAppServerSession", FakeRpcSession)
    monkeypatch.setattr("ii_agent.agents.codex_runtime.asyncio.sleep", AsyncMock())

    returned_handle, _returned_rpc = await agent._start_app_server(sandbox, run_id="run-123")

    assert returned_handle is handle
    assert captured["request"] == (
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
    assert captured["notify"] == ("initialized", {})


@pytest.mark.asyncio
async def test_codex_runtime_pauses_and_persists_checkpoint_for_approval(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    run_id = str(uuid.uuid4())
    persisted_checkpoints: list[CodexResumeCheckpoint] = []

    class FakeRpc:
        async def request(self, method: str, params: dict) -> dict:
            if method == "turn/start":
                return {"turn": {"id": "turn_123"}}
            raise AssertionError(f"Unexpected request: {method}")

        async def next_event(self, *, timeout: float = 0.25):
            if getattr(self, "_delivered", False):
                await asyncio.sleep(0)
                return None
            self._delivered = True
            return (
                "server_request",
                _CodexServerRequest(
                    raw_id="req_123",
                    method="item/commandExecution/requestApproval",
                    params={
                        "threadId": "thr_123",
                        "turnId": "turn_123",
                        "itemId": "item_123",
                        "command": ["git", "status"],
                        "cwd": "/workspace",
                        "availableDecisions": ["accept", "decline", "cancel"],
                    },
                ),
            )

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(
        agent,
        "_load_thread_binding",
        AsyncMock(return_value=SimpleNamespace(thread_id="thr_123", last_turn_id=None)),
    )
    monkeypatch.setattr(
        agent,
        "_start_or_resume_thread",
        AsyncMock(
            return_value=("thr_123", SimpleNamespace(thread_id="thr_123", last_turn_id=None))
        ),
    )
    monkeypatch.setattr(agent, "_persist_thread_binding", AsyncMock())
    monkeypatch.setattr(
        agent,
        "_persist_codex_resume_checkpoint",
        AsyncMock(
            side_effect=lambda *, run_id, checkpoint: persisted_checkpoints.append(checkpoint)
        ),
    )

    events = [
        event
        async for event in agent._arun_stream(
            input="Run Codex",
            run_id=run_id,
            images=None,
            files=None,
        )
    ]

    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[1], RunPausedEvent)
    assert persisted_checkpoints
    assert persisted_checkpoints[0].thread_id == "thr_123"
    assert persisted_checkpoints[0].turn_id == "turn_123"
    assert persisted_checkpoints[0].pending_request_id == "req_123"
    assert persisted_checkpoints[0].pending_request_kind == "approval"


@pytest.mark.asyncio
async def test_codex_continue_run_replies_to_resumed_approval(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    run_id = str(uuid.uuid4())
    responses: list[tuple[object, object]] = []

    class FakeRpc:
        def __init__(self) -> None:
            self._events = [
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id="req_123",
                        method="item/commandExecution/requestApproval",
                        params={
                            "threadId": "thr_123",
                            "turnId": "turn_123",
                            "itemId": "item_123",
                        },
                    ),
                ),
                (
                    "notification",
                    {
                        "method": "turn/completed",
                        "params": {
                            "turn": {"id": "turn_123", "status": "completed", "error": None}
                        },
                    },
                ),
            ]

        async def next_event(self, *, timeout: float = 0.25):
            if self._events:
                return self._events.pop(0)
            await asyncio.sleep(0)
            return None

        async def respond(self, request_id, *, result=None, error=None) -> None:
            responses.append((request_id, result if error is None else error))

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(agent, "_resume_thread", AsyncMock())
    monkeypatch.setattr(agent, "_persist_codex_resume_checkpoint", AsyncMock())

    checkpoint = CodexResumeCheckpoint(
        thread_id="thr_123",
        turn_id="turn_123",
        pending_request_id="req_123",
        pending_request_kind="approval",
        request_payload={
            "method": "item/commandExecution/requestApproval",
            "threadId": "thr_123",
            "turnId": "turn_123",
            "itemId": "item_123",
        },
        allowed_decisions=["accept", "acceptForSession", "decline", "cancel"],
    )

    events = [
        event
        async for event in agent.acontinue_run(
            run_id=run_id,
            stream=True,
            decision="approve_session",
            policy_patch={"execpolicy_amendment": ["bash", "-lc", "pytest"]},
            resume_checkpoint=checkpoint,
        )
    ]

    assert responses == [("req_123", {"decision": "acceptForSession"})]
    assert len(events) == 1
    assert isinstance(events[0], RunCompletedEvent)


@pytest.mark.asyncio
async def test_codex_continue_run_falls_back_to_single_use_accept_when_session_accept_is_unavailable(
    monkeypatch,
):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    responses: list[tuple[object, object]] = []

    class FakeRpc:
        def __init__(self) -> None:
            self._events = [
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id="req_123",
                        method="item/commandExecution/requestApproval",
                        params={
                            "threadId": "thr_123",
                            "turnId": "turn_123",
                            "itemId": "item_123",
                        },
                    ),
                ),
                (
                    "notification",
                    {
                        "method": "turn/completed",
                        "params": {
                            "turn": {"id": "turn_123", "status": "completed", "error": None}
                        },
                    },
                ),
            ]

        async def next_event(self, *, timeout: float = 0.25):
            if self._events:
                return self._events.pop(0)
            await asyncio.sleep(0)
            return None

        async def respond(self, request_id, *, result=None, error=None) -> None:
            responses.append((request_id, result if error is None else error))

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(agent, "_resume_thread", AsyncMock())
    monkeypatch.setattr(agent, "_persist_codex_resume_checkpoint", AsyncMock())

    checkpoint = CodexResumeCheckpoint(
        thread_id="thr_123",
        turn_id="turn_123",
        pending_request_id="req_123",
        pending_request_kind="approval",
        request_payload={
            "method": "item/commandExecution/requestApproval",
            "threadId": "thr_123",
            "turnId": "turn_123",
            "itemId": "item_123",
        },
        allowed_decisions=["accept", "decline", "cancel"],
    )

    events = [
        event
        async for event in agent.acontinue_run(
            run_id=str(uuid.uuid4()),
            stream=True,
            decision="approve_session",
            resume_checkpoint=checkpoint,
        )
    ]

    assert responses == [("req_123", {"decision": "accept"})]
    assert len(events) == 1
    assert isinstance(events[0], RunCompletedEvent)


@pytest.mark.asyncio
async def test_codex_continue_run_replies_to_resumed_user_input(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    responses: list[tuple[object, object]] = []

    class FakeRpc:
        def __init__(self) -> None:
            self._events = [
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id="req_input",
                        method="item/tool/requestUserInput",
                        params={
                            "threadId": "thr_123",
                            "turnId": "turn_123",
                            "itemId": "call_123",
                            "questions": [
                                {
                                    "id": "choice",
                                    "header": "Choice",
                                    "question": "Pick one",
                                    "options": [
                                        {"label": "Supabase", "description": "Managed Postgres"}
                                    ],
                                }
                            ],
                        },
                    ),
                ),
                (
                    "notification",
                    {
                        "method": "turn/completed",
                        "params": {
                            "turn": {"id": "turn_123", "status": "completed", "error": None}
                        },
                    },
                ),
            ]

        async def next_event(self, *, timeout: float = 0.25):
            if self._events:
                return self._events.pop(0)
            await asyncio.sleep(0)
            return None

        async def respond(self, request_id, *, result=None, error=None) -> None:
            responses.append((request_id, result if error is None else error))

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(agent, "_resume_thread", AsyncMock())
    monkeypatch.setattr(agent, "_persist_codex_resume_checkpoint", AsyncMock())

    checkpoint = CodexResumeCheckpoint(
        thread_id="thr_123",
        turn_id="turn_123",
        pending_request_id="req_input",
        pending_request_kind="user_input",
        request_payload={
            "method": "item/tool/requestUserInput",
            "threadId": "thr_123",
            "turnId": "turn_123",
            "itemId": "call_123",
        },
    )

    events = [
        event
        async for event in agent.acontinue_run(
            run_id=str(uuid.uuid4()),
            stream=True,
            decision="approve_once",
            user_input={"choice": "Supabase"},
            resume_checkpoint=checkpoint,
        )
    ]

    assert responses == [("req_input", {"answers": {"choice": {"answers": ["Supabase"]}}})]
    assert len(events) == 1
    assert isinstance(events[0], RunCompletedEvent)


@pytest.mark.asyncio
async def test_codex_runtime_executes_registered_dynamic_tool_and_stops(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    responses: list[tuple[object, object]] = []
    tool_inputs: list[dict] = []

    class FakeTool:
        name = "submit_plan"
        description = "Submit a plan"
        input_schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
        stop_after_tool_call = True

        async def execute(self, tool_input: dict) -> ToolResult:
            tool_inputs.append(tool_input)
            return ToolResult(
                llm_content=f"submitted {tool_input['summary']}",
                is_error=False,
                is_interrupted=True,
            )

    agent.add_tool(FakeTool())

    class FakeRpc:
        def __init__(self) -> None:
            self._events = [
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id="req_tool",
                        method="item/tool/call",
                        params={
                            "threadId": "thr_123",
                            "turnId": "turn_123",
                            "callId": "call_123",
                            "tool": "submit_plan",
                            "arguments": {"summary": "demo"},
                        },
                    ),
                ),
            ]

        async def request(self, method: str, params: dict) -> dict:
            if method == "turn/start":
                return {"turn": {"id": "turn_123"}}
            raise AssertionError(f"Unexpected request: {method}")

        async def next_event(self, *, timeout: float = 0.25):
            if self._events:
                return self._events.pop(0)
            await asyncio.sleep(0)
            return None

        async def respond(self, request_id, *, result=None, error=None) -> None:
            responses.append((request_id, result if error is None else error))

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(
        agent,
        "_load_thread_binding",
        AsyncMock(return_value=SimpleNamespace(thread_id="thr_123", last_turn_id=None)),
    )
    monkeypatch.setattr(
        agent,
        "_start_or_resume_thread",
        AsyncMock(
            return_value=("thr_123", SimpleNamespace(thread_id="thr_123", last_turn_id=None))
        ),
    )
    monkeypatch.setattr(agent, "_persist_thread_binding", AsyncMock())

    events = [
        event
        async for event in agent._arun_stream(
            input="Run Codex",
            run_id=str(uuid.uuid4()),
            images=None,
            files=None,
        )
    ]

    assert tool_inputs == [{"summary": "demo"}]
    assert responses == [
        (
            "req_tool",
            {
                "contentItems": [{"type": "inputText", "text": "submitted demo"}],
                "success": True,
            },
        )
    ]
    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[-1], RunCompletedEvent)
    assert events[-1].content == "submitted demo"


@pytest.mark.asyncio
async def test_codex_runtime_pauses_and_persists_checkpoint_for_user_input(monkeypatch):
    agent = CodexRuntimeAgent(
        user_id="00000000-0000-0000-0000-000000000101",
        session_id="00000000-0000-0000-0000-000000000202",
        llm_config=LLMConfig(model="gpt-5.4", provider=Provider.OPENAI, runtime_product="codex"),
        name="codex_agent",
        system_message="Follow repo instructions.",
    )
    run_id = str(uuid.uuid4())
    persisted_checkpoints: list[CodexResumeCheckpoint] = []

    class FakeRpc:
        def __init__(self) -> None:
            self._events = [
                (
                    "server_request",
                    _CodexServerRequest(
                        raw_id="req_input",
                        method="item/tool/requestUserInput",
                        params={
                            "threadId": "thr_123",
                            "turnId": "turn_123",
                            "itemId": "call_123",
                            "questions": [
                                {
                                    "id": "choice",
                                    "header": "Choice",
                                    "question": "Pick one",
                                    "options": [
                                        {"label": "Supabase", "description": "Managed Postgres"}
                                    ],
                                }
                            ],
                        },
                    ),
                ),
            ]

        async def request(self, method: str, params: dict) -> dict:
            if method == "turn/start":
                return {"turn": {"id": "turn_123"}}
            raise AssertionError(f"Unexpected request: {method}")

        async def next_event(self, *, timeout: float = 0.25):
            if self._events:
                return self._events.pop(0)
            await asyncio.sleep(0)
            return None

        def debug_output(self) -> str:
            return ""

    monkeypatch.setattr(agent, "_ensure_sandbox", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        agent, "_start_app_server", AsyncMock(return_value=(MagicMock(), FakeRpc()))
    )
    monkeypatch.setattr(
        agent,
        "_load_thread_binding",
        AsyncMock(return_value=SimpleNamespace(thread_id="thr_123", last_turn_id=None)),
    )
    monkeypatch.setattr(
        agent,
        "_start_or_resume_thread",
        AsyncMock(
            return_value=("thr_123", SimpleNamespace(thread_id="thr_123", last_turn_id=None))
        ),
    )
    monkeypatch.setattr(agent, "_persist_thread_binding", AsyncMock())
    monkeypatch.setattr(
        agent,
        "_persist_codex_resume_checkpoint",
        AsyncMock(
            side_effect=lambda *, run_id, checkpoint: persisted_checkpoints.append(checkpoint)
        ),
    )

    events = [
        event
        async for event in agent._arun_stream(
            input="Run Codex",
            run_id=run_id,
            images=None,
            files=None,
        )
    ]

    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[-1], RunPausedEvent)
    assert persisted_checkpoints
    assert persisted_checkpoints[0].pending_request_kind == "user_input"
    assert persisted_checkpoints[0].thread_id == "thr_123"
    assert persisted_checkpoints[0].turn_id == "turn_123"
    assert events[-1].tools[0].requires_user_input is True
    assert events[-1].tools[0].user_input_schema[0].name == "choice"


@pytest.mark.asyncio
async def test_codex_app_server_session_ignores_echoed_client_requests():
    handle = _FakeHandle()
    rpc = _CodexAppServerSession(handle=handle)

    request_task = asyncio.create_task(
        rpc.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ii_agent",
                    "title": "II Agent",
                    "version": "0.1.0",
                }
            },
        )
    )
    await asyncio.sleep(0)

    rpc.feed_data(
        b'{"method":"initialize","id":1,"params":{"clientInfo":{"name":"ii_agent","title":"II Agent","version":"0.1.0"}}}\n'
    )
    await asyncio.sleep(0)
    rpc.feed_data(b'{"id":1,"result":{"userAgent":"codex-test"}}\n')

    result = await request_task

    assert result == {"userAgent": "codex-test"}
    assert handle.send_input.await_count == 1


def test_codex_app_server_bootstrap_command_disables_tty_echo():
    command = _app_server_bootstrap_command()

    assert command.startswith("stty -echo -icanon min 1 time 0; ")
    assert "exec codex app-server --listen stdio://" in command


def test_normalize_pty_log_line_filters_json_and_bootstrap_noise():
    assert (
        _normalize_pty_log_line(
            '\x1b[31m{"method":"thread/started","params":{"thread":{"id":"thr"}}}\x1b[0m'
        )
        is None
    )
    assert (
        _normalize_pty_log_line(
            "stty -echo -icanon min 1 time 0; exec codex app-server --listen stdio://"
        )
        is None
    )
    assert _normalize_pty_log_line("\x1b[31mfailed to connect to websocket\x1b[0m") == (
        "failed to connect to websocket"
    )


def test_codex_pty_log_mirror_logs_non_json_lines(monkeypatch):
    mirror = _CodexPtyLogMirror(
        session_id="00000000-0000-0000-0000-000000000202",
        run_id="run-123",
    )
    info = MagicMock()
    monkeypatch.setattr("ii_agent.agents.codex_runtime.logger.info", info)

    mirror.feed_data(b"\x1b[31mfailed to connect to websocket\x1b[0m\n")
    mirror.feed_data(b'{"method":"thread/started","params":{"thread":{"id":"thr"}}}\n')

    info.assert_called_once_with(
        "[codex-pty][session=00000000-0000-0000-0000-000000000202][run=run-123] "
        "failed to connect to websocket"
    )
