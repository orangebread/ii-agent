from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ii_agent.agents.sandboxes.docker import (
    DockerSandbox,
    _FILE_READ_SCRIPT,
    _FILE_WRITE_SCRIPT,
    _ProcessResult,
)
from ii_agent.agents.sandboxes.exceptions import SandboxOperationError
from ii_agent.agents.sandboxes.types import SandboxStatus


pytestmark = pytest.mark.unit


def _result(*, exit_code: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> _ProcessResult:
    return _ProcessResult(exit_code=exit_code, stdout=stdout, stderr=stderr)


@pytest.mark.asyncio
async def test_create_builds_default_runtime_image_when_missing(monkeypatch, settings_factory):
    settings = settings_factory(
        sandbox={
            "docker_image": "ii-agent-codex-sandbox:local",
            "codex_cli_version": "0.124.0",
            "timeout_seconds": 900,
            "user": "/home/user",
        }
    )
    monkeypatch.setenv("DEV_PROJECT_NAME", "ii-agent-dev")
    calls: list[tuple[list[str], bytes | None, int | float | None]] = []
    responses = iter(
        [
            _result(exit_code=1, stderr=b"missing"),
            _result(exit_code=1, stderr=b"missing"),
            _result(stdout=b"built"),
            _result(stdout=b"container-123\n"),
        ]
    )

    async def fake_run(args, *, input_bytes=None, timeout=None):
        calls.append((args, input_bytes, timeout))
        return next(responses)

    monkeypatch.setattr("ii_agent.agents.sandboxes.docker.get_settings", lambda: settings)
    monkeypatch.setattr(
        "ii_agent.agents.sandboxes.docker._resolve_runtime_binary", lambda: "docker"
    )
    monkeypatch.setattr("ii_agent.agents.sandboxes.docker._run_subprocess", fake_run)

    sandbox = await DockerSandbox.create("sandbox-1", "session-1")

    assert sandbox.provider_sandbox_id == "container-123"
    assert sandbox.status == SandboxStatus.RUNNING
    assert calls[2][0][:3] == ["docker", "build", "-t"]
    assert b"@openai/codex@0.124.0" in (calls[2][1] or b"")
    assert calls[3][0][:3] == ["docker", "run", "-d"]
    assert "ii_agent.managed=true" in calls[3][0]
    assert "ii_agent.role=sandbox" in calls[3][0]
    assert "ii_agent.project_name=ii-agent-dev" in calls[3][0]


@pytest.mark.asyncio
async def test_run_command_starts_container_before_exec(monkeypatch, settings_factory):
    settings = settings_factory(sandbox={"docker_image": "ii-agent-codex-sandbox:local"})
    sandbox = DockerSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="container-123",
        config=settings,
        runtime_binary="docker",
    )
    calls: list[list[str]] = []
    responses = iter(
        [
            _result(stdout=b"exited\n"),
            _result(stdout=b"container-123\n"),
            _result(stdout=b"/workspace\n"),
        ]
    )

    async def fake_run(args, *, input_bytes=None, timeout=None):
        del input_bytes, timeout
        calls.append(args)
        return next(responses)

    monkeypatch.setattr("ii_agent.agents.sandboxes.docker._run_subprocess", fake_run)

    output = await sandbox.run_command("pwd", cwd="/workspace")

    assert output == "/workspace\n"
    assert calls[1] == ["docker", "start", "container-123"]
    assert calls[2][:6] == ["docker", "exec", "-w", "/workspace", "container-123", "bash"]
    assert calls[2][-2:] == ["-lc", "pwd"]


@pytest.mark.asyncio
async def test_write_file_streams_bytes_into_container(monkeypatch, settings_factory):
    settings = settings_factory(sandbox={"docker_image": "ii-agent-codex-sandbox:local"})
    sandbox = DockerSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="container-123",
        config=settings,
        runtime_binary="docker",
    )
    monkeypatch.setattr(sandbox, "_ensure_container_running", AsyncMock())
    run = AsyncMock(return_value=_result())
    monkeypatch.setattr("ii_agent.agents.sandboxes.docker._run_subprocess", run)

    info = await sandbox.write_file("/workspace/demo.txt", "hello")

    assert info.path == "/workspace/demo.txt"
    run.assert_awaited_once()
    args = run.await_args.args[0]
    assert args[:7] == [
        "docker",
        "exec",
        "-i",
        "container-123",
        "python3",
        "-c",
        _FILE_WRITE_SCRIPT,
    ]
    assert args[7] == "/workspace/demo.txt"
    assert run.await_args.kwargs["input_bytes"] == b"hello"


@pytest.mark.asyncio
async def test_download_file_returns_text(monkeypatch, settings_factory):
    settings = settings_factory(sandbox={"docker_image": "ii-agent-codex-sandbox:local"})
    sandbox = DockerSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="container-123",
        config=settings,
        runtime_binary="docker",
    )
    monkeypatch.setattr(sandbox, "_ensure_container_running", AsyncMock())
    run = AsyncMock(return_value=_result(stdout=b"hello"))
    monkeypatch.setattr("ii_agent.agents.sandboxes.docker._run_subprocess", run)

    content = await sandbox.download_file("/workspace/demo.txt", format="text")

    assert content == "hello"
    args = run.await_args.args[0]
    assert args[:7] == ["docker", "exec", "-i", "container-123", "python3", "-c", _FILE_READ_SCRIPT]
    assert args[7] == "/workspace/demo.txt"


@pytest.mark.asyncio
async def test_expose_port_is_explicitly_unsupported(settings_factory):
    settings = settings_factory(sandbox={"docker_image": "ii-agent-codex-sandbox:local"})
    sandbox = DockerSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="container-123",
        config=settings,
        runtime_binary="docker",
    )

    with pytest.raises(SandboxOperationError, match="Port exposure is not supported"):
        await sandbox.expose_port(6060)
