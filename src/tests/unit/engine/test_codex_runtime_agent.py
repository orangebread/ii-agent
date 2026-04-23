from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ii_agent.agents.codex_runtime import (
    CodexRuntimeAgent,
    _CodexAppServerSession,
    _CodexPtyLogMirror,
    _app_server_bootstrap_command,
    _normalize_pty_log_line,
)
from ii_agent.agents.runs.agent import RunErrorEvent
from ii_agent.core.config.llm_config import LLMConfig
from ii_agent.files import File, Image
from ii_agent.settings.llm import Provider


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
    assert params["approvalPolicy"] == "never"
    assert params["sandbox"] == "workspace-write"
    assert params["input"][0]["type"] == "text"
    assert params["input"][1] == {"type": "localImage", "path": "/workspace/screenshot.png"}


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
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
                "personality": "pragmatic",
                "model": "gpt-5.4",
                "serviceName": "ii_agent",
                "sessionStartSource": "startup",
            },
        )
    ]


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
            run_id="run-123",
            images=None,
            files=None,
        )
    ]

    assert len(events) == 1
    assert isinstance(events[0], RunErrorEvent)
    assert events[0].content == "sandbox bootstrap failed"


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
