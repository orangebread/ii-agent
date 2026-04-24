from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ii_agent.agents.sandboxes.daytona import DaytonaSandbox, _DaytonaFileInfo
from ii_agent.agents.sandboxes.exceptions import SandboxOperationError
from ii_agent.agents.sandboxes.types import SandboxStatus


pytestmark = pytest.mark.unit


def _settings(settings_factory):
    return settings_factory(
        sandbox={
            "provider": "daytona",
            "timeout_seconds": 900,
            "user": "/home/user",
            "daytona_api_url": "http://daytona.local/api",
            "daytona_api_key": "daytona-key",
            "daytona_target": "local",
            "daytona_default_image": "ii-agent-codex-sandbox:local",
            "daytona_snapshot": None,
            "daytona_auto_stop_interval": 15,
            "daytona_ephemeral": True,
            "daytona_public_preview": True,
            "daytona_network_block_all": False,
            "daytona_network_allow_list": ["api.openai.com"],
        },
        mcp={"timeout": 30},
        vscode_port=8080,
    )


def test_build_create_payload_uses_image_defaults(settings_factory):
    settings = _settings(settings_factory)

    payload = DaytonaSandbox._build_create_payload(
        settings,
        "sandbox-1",
        {"session_id": "session-1"},
    )

    assert payload["target"] == "local"
    assert payload["labels"]["session_id"] == "session-1"
    assert payload["networkAllowList"] == "api.openai.com"
    assert payload["autoDeleteInterval"] == 15
    assert payload["buildInfo"]["dockerfileContent"] == "FROM ii-agent-codex-sandbox:local\n"


def test_build_create_payload_prefers_snapshot(settings_factory):
    settings = _settings(settings_factory)
    settings.sandbox.daytona_snapshot = "snapshot-1"

    payload = DaytonaSandbox._build_create_payload(settings, "sandbox-1", {})

    assert payload["snapshot"] == "snapshot-1"
    assert "buildInfo" not in payload


@pytest.mark.asyncio
async def test_run_command_posts_to_daytona_toolbox(settings_factory, monkeypatch):
    sandbox = DaytonaSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="daytona-1",
        status=SandboxStatus.RUNNING,
        sandbox={"toolboxProxyUrl": "http://toolbox.local"},
        config=_settings(settings_factory),
    )
    monkeypatch.setattr(sandbox, "_ensure_sandbox_connection", AsyncMock())
    request = AsyncMock(return_value={"exitCode": 0, "result": "hello\n"})
    monkeypatch.setattr(sandbox, "_toolbox_request", request)

    output = await sandbox.run_command("echo hello", cwd="/workspace", timeout=10)

    assert output == "hello\n"
    request.assert_awaited_once_with(
        "POST",
        "/process/execute",
        json={"command": "echo hello", "cwd": "/workspace", "timeout": 10},
        timeout=15,
    )


@pytest.mark.asyncio
async def test_run_command_raises_with_exit_context(settings_factory, monkeypatch):
    sandbox = DaytonaSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="daytona-1",
        status=SandboxStatus.RUNNING,
        sandbox={"toolboxProxyUrl": "http://toolbox.local"},
        config=_settings(settings_factory),
    )
    monkeypatch.setattr(sandbox, "_ensure_sandbox_connection", AsyncMock())
    monkeypatch.setattr(
        sandbox,
        "_toolbox_request",
        AsyncMock(return_value={"exitCode": 2, "result": "bad command"}),
    )

    with pytest.raises(SandboxOperationError, match="exit code 2"):
        await sandbox.run_command("bad")


@pytest.mark.asyncio
async def test_list_files_with_contents_inlines_small_text_files(settings_factory, monkeypatch):
    sandbox = DaytonaSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="daytona-1",
        status=SandboxStatus.RUNNING,
        sandbox={"toolboxProxyUrl": "http://toolbox.local"},
        config=_settings(settings_factory),
    )

    async def fake_list_directory(path: str):
        if path == "/workspace":
            return [
                _DaytonaFileInfo("src", "/workspace/src", True),
                _DaytonaFileInfo("README.md", "/workspace/README.md", False, size=9),
            ]
        if path == "/workspace/src":
            return [_DaytonaFileInfo("app.py", "/workspace/src/app.py", False, size=10)]
        return []

    async def fake_read_file_content(path: str, *, skip_metadata_check: bool = False):
        del skip_metadata_check
        return SimpleNamespace(
            path=path,
            file_kind="text",
            content=f"content:{path}",
            language="python" if path.endswith(".py") else "markdown",
        )

    monkeypatch.setattr(sandbox, "_list_directory", fake_list_directory)
    monkeypatch.setattr(sandbox, "read_file_content", fake_read_file_content)

    tree, contents = await sandbox.list_files_with_contents("/workspace")

    assert tree.children[0].path == "/workspace/src"
    assert contents["/workspace/README.md"]["language"] == "markdown"
    assert contents["/workspace/src/app.py"]["content"] == "content:/workspace/src/app.py"


@pytest.mark.asyncio
async def test_list_directory_uses_daytona_slash_route(settings_factory, monkeypatch):
    sandbox = DaytonaSandbox(
        sandbox_id="sandbox-1",
        session_id="session-1",
        provider_sandbox_id="daytona-1",
        status=SandboxStatus.RUNNING,
        sandbox={"toolboxProxyUrl": "http://toolbox.local"},
        config=_settings(settings_factory),
    )
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(sandbox, "_toolbox_request", request)

    assert await sandbox._list_directory("/workspace") == []
    request.assert_awaited_once_with("GET", "/files/", params={"path": "/workspace"})
