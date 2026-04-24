import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import types
import sys

import pytest

from ii_agent.agents.sandboxes.shell import (
    ShellExecutionRequest,
    ShellOperationError,
    ShellResult,
    ShellSessionRecord,
    ShellSessionState,
)
from ii_agent.agents.sandboxes.exceptions import (
    SandboxNotFoundException,
    SandboxOperationError as SandboxProviderOperationError,
)
from ii_agent.agents.sandboxes.service import SandboxService
from ii_agent.agents.sandboxes.types import SandboxProviderType, SandboxStatus
from ii_agent.settings.mcp.schemas import MCPServersConfig, MCPSettingInfo


class FakeSandboxRepo:
    def __init__(self, records_by_session_id):
        self.records_by_session_id = records_by_session_id

    async def get_active_by_session_id(self, db, session_id):
        return self.records_by_session_id.get(session_id)


class FakeSessionRepo:
    def __init__(self, sessions_by_id):
        self.sessions_by_id = sessions_by_id

    async def get_by_id(self, db, session_id):
        return self.sessions_by_id.get(session_id)


@asynccontextmanager
async def _noop_db_cm():
    yield None


def _make_record(
    *,
    status: ShellSessionState = ShellSessionState.IDLE,
    prompt_seq: int = 7,
    pending_prompt_seq: int | None = None,
) -> ShellSessionRecord:
    return ShellSessionRecord(
        pid=123,
        cwd="/workspace/project",
        log_path="/workspace/.ii_agent/pty/build.log",
        state_path="/workspace/.ii_agent/pty/build.state",
        status=status,
        prompt_seq=prompt_seq,
        pending_prompt_seq=pending_prompt_seq,
        updated_at="2026-04-02T00:00:00+00:00",
    )


def _make_connected_shell(
    monkeypatch, service, *, sessions: dict[str, ShellSessionRecord] | None = None
):
    shell = MagicMock()
    shell.workspace_path = "/workspace"
    shell.max_timeout = 180
    shell.poll_interval = 0
    shell.validate_session_name = MagicMock()
    shell.normalize_directory = AsyncMock(side_effect=lambda directory: directory)
    shell.is_session_live = AsyncMock(return_value=True)
    shell.refresh_session_record = AsyncMock(side_effect=lambda record: (record, False))
    shell.send_stdin = AsyncMock()
    shell.wait_for_prompt = AsyncMock()
    shell.read_command_output = AsyncMock(
        return_value=ShellResult(clean_output="ok", ansi_output="ok")
    )
    shell.read_session_output = AsyncMock(
        return_value=ShellResult(clean_output="tail", ansi_output="tail")
    )

    sandbox = SimpleNamespace(shell=shell, sandbox_id=str(uuid.uuid4()))
    monkeypatch.setattr(service, "get_sandbox_for_session", AsyncMock(return_value=sandbox))
    monkeypatch.setattr(
        "ii_agent.agents.sandboxes.service.get_db_session_local",
        lambda: _noop_db_cm(),
    )
    monkeypatch.setattr(
        service,
        "load_provider_data",
        AsyncMock(
            return_value={
                "provider": "e2b",
                "pty_sessions": {
                    session_name: record.model_dump(mode="json")
                    for session_name, record in (sessions or {}).items()
                },
            }
        ),
    )
    monkeypatch.setattr(service, "persist_provider_data", AsyncMock())
    return sandbox, shell


@pytest.mark.asyncio
async def test_get_by_session_id_falls_back_to_parent_session(settings_factory):
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    parent_record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=parent_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-parent",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={"source": "parent"},
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({parent_id: parent_record}),
        session_repo=FakeSessionRepo(
            {
                child_id: SimpleNamespace(id=child_id, parent_session_id=parent_id),
            }
        ),
        config=settings_factory(),
    )

    record = await service.get_by_session_id(None, child_id)

    assert record is parent_record


@pytest.mark.asyncio
async def test_get_sandbox_for_session_uses_parent_sandbox_for_fork(settings_factory, monkeypatch):
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    parent_record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=parent_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-parent",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={"source": "parent"},
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({parent_id: parent_record}),
        session_repo=FakeSessionRepo(
            {
                child_id: SimpleNamespace(id=child_id, parent_session_id=parent_id),
            }
        ),
        config=settings_factory(),
    )
    expected_sandbox = SimpleNamespace(provider_sandbox_id="sbx-parent")

    async def fake_connect(record):
        assert record is parent_record
        return expected_sandbox

    monkeypatch.setattr(service, "_connect_provider", fake_connect)

    sandbox = await service.get_sandbox_for_session(None, child_id)

    assert sandbox is expected_sandbox


@pytest.mark.asyncio
async def test_get_sandbox_for_session_propagates_provider_connection_errors(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-1",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={},
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({session_id: record}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )

    async def fake_connect(_record):
        raise RuntimeError("e2b unavailable")

    monkeypatch.setattr(service, "_connect_provider", fake_connect)

    with pytest.raises(RuntimeError, match="e2b unavailable"):
        await service.get_sandbox_for_session(None, session_id)


@pytest.mark.asyncio
async def test_get_sandbox_for_session_recreates_missing_docker_provider_after_local_cleanup(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.DOCKER,
        provider_sandbox_id="docker-old",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={},
    )
    expected_sandbox = SimpleNamespace(provider_sandbox_id="docker-new")
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({session_id: record}),
        session_repo=FakeSessionRepo(
            {
                session_id: SimpleNamespace(id=session_id, user_id=user_id),
            }
        ),
        config=settings_factory(sandbox={"provider": "docker"}),
    )
    monkeypatch.setattr(
        service,
        "_connect_provider",
        AsyncMock(side_effect=SandboxNotFoundException("docker-old")),
    )
    init_sandbox = AsyncMock(return_value=expected_sandbox)
    monkeypatch.setattr(service, "init_sandbox", init_sandbox)

    sandbox = await service.get_sandbox_for_session(None, session_id)

    assert sandbox is expected_sandbox
    init_sandbox.assert_awaited_once_with(
        None,
        session_id=session_id,
        user_id=user_id,
    )


@pytest.mark.asyncio
async def test_create_provider_routes_docker_records_to_docker_provider(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.DOCKER,
        provider_sandbox_id=None,
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "docker"}),
    )
    expected = SimpleNamespace(provider_sandbox_id="docker-123")
    create = AsyncMock(return_value=expected)
    monkeypatch.setattr("ii_agent.agents.sandboxes.service.DockerSandbox.create", create)

    result = await service._create_provider(record, metadata={"tool": "codex"})

    assert result is expected
    create.assert_awaited_once_with(
        sandbox_id=str(record.id),
        session_id=str(record.session_id),
        metadata={"tool": "codex"},
    )


@pytest.mark.asyncio
async def test_connect_provider_routes_docker_records_to_docker_provider(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.DOCKER,
        provider_sandbox_id="docker-123",
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "docker"}),
    )
    expected = SimpleNamespace(provider_sandbox_id="docker-123")
    connect = AsyncMock(return_value=expected)
    monkeypatch.setattr("ii_agent.agents.sandboxes.service.DockerSandbox.connect", connect)

    result = await service._connect_provider(record)

    assert result is expected
    connect.assert_awaited_once_with(
        sandbox_id=str(record.id),
        session_id=str(record.session_id),
        provider_sandbox_id="docker-123",
    )


@pytest.mark.asyncio
async def test_create_provider_routes_daytona_records_to_daytona_provider(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.DAYTONA,
        provider_sandbox_id=None,
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "daytona"}),
    )
    expected = SimpleNamespace(provider_sandbox_id="daytona-123")
    create = AsyncMock(return_value=expected)
    monkeypatch.setattr("ii_agent.agents.sandboxes.service.DaytonaSandbox.create", create)

    result = await service._create_provider(record, metadata={"tool": "codex"})

    assert result is expected
    create.assert_awaited_once_with(
        sandbox_id=str(record.id),
        session_id=str(record.session_id),
        metadata={"tool": "codex"},
    )


@pytest.mark.asyncio
async def test_connect_provider_routes_daytona_records_to_daytona_provider(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    record = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        provider=SandboxProviderType.DAYTONA,
        provider_sandbox_id="daytona-123",
    )
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "daytona"}),
    )
    expected = SimpleNamespace(provider_sandbox_id="daytona-123")
    connect = AsyncMock(return_value=expected)
    monkeypatch.setattr("ii_agent.agents.sandboxes.service.DaytonaSandbox.connect", connect)

    result = await service._connect_provider(record)

    assert result is expected
    connect.assert_awaited_once_with(
        sandbox_id=str(record.id),
        session_id=str(record.session_id),
        provider_sandbox_id="daytona-123",
    )


def test_resolve_provider_supports_daytona(settings_factory):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "daytona"}),
    )

    assert service._resolve_provider() == SandboxProviderType.DAYTONA


@pytest.mark.asyncio
async def test_get_sandbox_by_session_id_aliases_existing_lookup(settings_factory, monkeypatch):
    session_id = uuid.uuid4()
    expected_sandbox = SimpleNamespace(provider_sandbox_id="sbx-1")
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )

    get_sandbox_for_session = AsyncMock(return_value=expected_sandbox)
    monkeypatch.setattr(service, "get_sandbox_for_session", get_sandbox_for_session)

    sandbox = await service.get_sandbox_by_session_id(None, str(session_id))

    assert sandbox is expected_sandbox
    get_sandbox_for_session.assert_awaited_once_with(None, session_id=session_id)


@pytest.mark.asyncio
async def test_get_sandbox_by_session_loads_user_from_session_when_db_is_implicit(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    expected_sandbox = SimpleNamespace(provider_sandbox_id="sbx-1")
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo(
            {
                session_id: SimpleNamespace(id=session_id, user_id=user_id),
            }
        ),
        config=settings_factory(),
    )

    init_sandbox = AsyncMock(return_value=expected_sandbox)
    monkeypatch.setattr(service, "init_sandbox", init_sandbox)
    monkeypatch.setattr(
        "ii_agent.agents.sandboxes.service.get_db_session_local",
        lambda: _noop_db_cm(),
    )

    sandbox = await service.get_sandbox_by_session(session_id)

    assert sandbox is expected_sandbox
    init_sandbox.assert_awaited_once_with(
        None,
        session_id=session_id,
        user_id=user_id,
    )


class _FakeMCPClient:
    instances = []

    def __init__(self, sandbox_url):
        self.sandbox_url = sandbox_url
        self.register_codex = AsyncMock()
        self.register_custom_mcp = AsyncMock()
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_register_user_mcp_servers_registers_selected_codex(monkeypatch, settings_factory):
    session_id = uuid.uuid4()
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    custom_setting = MCPSettingInfo(
        id=uuid.uuid4(),
        mcp_config=MCPServersConfig.model_validate(
            {"mcpServers": {"custom-server": {"command": "npx", "args": ["custom"]}}}
        ),
        metadata=None,
        is_active=True,
        created_at="2026-04-16T00:00:00+00:00",
        updated_at=None,
    )
    selected_runtime = SimpleNamespace(
        provider_connection_id=uuid.uuid4(),
        mcp_metadata={"tool_type": "codex"},
        mcp_config={"mcpServers": {"codex-as-mcp": {"command": "uvx"}}},
    )
    sandbox = SimpleNamespace(
        session_id=str(session_id),
        write_file=AsyncMock(),
    )

    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.list_mcp_settings",
        AsyncMock(return_value=SimpleNamespace(settings=[custom_setting])),
    )
    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.resolve_effective_runtime_setting",
        AsyncMock(return_value=selected_runtime),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_connection_model",
        AsyncMock(return_value=SimpleNamespace(id=selected_runtime.provider_connection_id)),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_credentials_dict",
        lambda self, connection: {
            "tokens": {
                "id_token": "id-123",
                "access_token": "access-123",
                "refresh_token": "refresh-123",
            }
        },
    )
    monkeypatch.setattr(service, "_get_composio_mcp_servers", AsyncMock(return_value=None))
    sys.modules["ii_server.mcp.client"] = types.SimpleNamespace(MCPClient=_FakeMCPClient)

    await service._register_user_mcp_servers(sandbox, uuid.uuid4(), "http://sandbox", None)

    sandbox.write_file.assert_awaited()
    client = _FakeMCPClient.instances[-1]
    client.register_codex.assert_awaited_once()
    client.register_custom_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_user_mcp_servers_registers_selected_claude(monkeypatch, settings_factory):
    session_id = uuid.uuid4()
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    selected_runtime = SimpleNamespace(
        provider_connection_id=uuid.uuid4(),
        mcp_metadata={"tool_type": "claude_code"},
        mcp_config={"mcpServers": {"claude-code-mcp": {"command": "npx"}}},
    )
    sandbox = SimpleNamespace(
        session_id=str(session_id),
        write_file=AsyncMock(),
    )

    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.list_mcp_settings",
        AsyncMock(return_value=SimpleNamespace(settings=[])),
    )
    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.resolve_effective_runtime_setting",
        AsyncMock(return_value=selected_runtime),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_connection_model",
        AsyncMock(return_value=SimpleNamespace(id=selected_runtime.provider_connection_id)),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_credentials_dict",
        lambda self, connection: {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    )
    monkeypatch.setattr(service, "_get_composio_mcp_servers", AsyncMock(return_value=None))
    sys.modules["ii_server.mcp.client"] = types.SimpleNamespace(MCPClient=_FakeMCPClient)

    await service._register_user_mcp_servers(sandbox, uuid.uuid4(), "http://sandbox", None)

    sandbox.write_file.assert_awaited()
    client = _FakeMCPClient.instances[-1]
    client.register_codex.assert_not_awaited()
    client.register_custom_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_configure_mcp_still_materializes_codex_auth_when_port_exposure_unavailable(
    monkeypatch, settings_factory
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"user": "/home/user"}),
    )
    selected_runtime = SimpleNamespace(
        provider_connection_id=uuid.uuid4(),
        mcp_metadata={"tool_type": "codex"},
        mcp_config={"mcpServers": {"codex-as-mcp": {"command": "uvx"}}},
    )
    sandbox = SimpleNamespace(
        session_id=str(session_id),
        sandbox_id="sandbox-1",
        expose_port=AsyncMock(
            side_effect=SandboxProviderOperationError(
                "expose_port",
                "Port exposure is not supported by the Docker sandbox provider yet.",
            )
        ),
        get_mcp_client=MagicMock(),
        write_file=AsyncMock(),
    )

    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.list_mcp_settings",
        AsyncMock(return_value=SimpleNamespace(settings=[])),
    )
    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.MCPSettingService.resolve_effective_runtime_setting",
        AsyncMock(return_value=selected_runtime),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_connection_model",
        AsyncMock(return_value=SimpleNamespace(id=selected_runtime.provider_connection_id)),
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.ProviderConnectionService.get_credentials_dict",
        lambda self, connection: {
            "tokens": {
                "id_token": "id-123",
                "access_token": "access-123",
                "refresh_token": "refresh-123",
            }
        },
    )
    monkeypatch.setattr(service, "_get_composio_mcp_servers", AsyncMock(return_value=None))

    await service._configure_mcp(sandbox, user_id, None)

    sandbox.write_file.assert_awaited_once()
    assert sandbox.write_file.await_args.args[0] == "/home/user/.codex/auth.json"
    auth_json = json.loads(sandbox.write_file.await_args.args[1])
    assert auth_json["auth_mode"] == "chatgpt"
    assert auth_json["OPENAI_API_KEY"] is None
    assert auth_json["tokens"]["id_token"] == "id-123"
    assert auth_json["tokens"]["access_token"] == "access-123"
    assert auth_json["tokens"]["refresh_token"] == "refresh-123"
    sandbox.get_mcp_client.assert_not_called()


@pytest.mark.asyncio
async def test_get_sandbox_by_session_accepts_db_first_and_normalizes_user_id(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = object()
    expected_sandbox = SimpleNamespace(provider_sandbox_id="sbx-1")
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )

    init_sandbox = AsyncMock(return_value=expected_sandbox)
    monkeypatch.setattr(service, "init_sandbox", init_sandbox)

    sandbox = await service.get_sandbox_by_session(
        db,
        session_id=session_id,
        user_id=str(user_id),
    )

    assert sandbox is expected_sandbox
    init_sandbox.assert_awaited_once_with(
        db,
        session_id=session_id,
        user_id=user_id,
    )


@pytest.mark.asyncio
async def test_init_sandbox_merges_persisted_provider_data_on_reconnect(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    record = SimpleNamespace(
        id=sandbox_id,
        session_id=session_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={
            "pty_sessions": {"build": {"pid": 123}},
            "ii_agent_secret_sync": {
                "revision": "persisted-revision",
                "project_path": "/workspace/app",
            },
        },
    )
    sandbox_mgr = SimpleNamespace(
        sandbox_id=str(sandbox_id),
        session_id=str(session_id),
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        metadata={
            "ii_sandbox_id": str(sandbox_id),
            "session_id": str(session_id),
            "template_id": "template-1",
        },
    )
    sandbox_repo = AsyncMock()
    sandbox_repo.update_provider_info = AsyncMock()
    service = SandboxService(
        sandbox_repo=sandbox_repo,
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    monkeypatch.setattr(service, "_resolve_sandbox_record", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "_connect_provider", AsyncMock(return_value=sandbox_mgr))
    monkeypatch.setattr(service, "_configure_mcp", AsyncMock())

    result = await service.init_sandbox(
        object(),
        session_id=session_id,
        user_id=user_id,
    )

    assert result is sandbox_mgr
    persisted_provider_data = sandbox_repo.update_provider_info.await_args.kwargs["provider_data"]
    assert persisted_provider_data["pty_sessions"] == {"build": {"pid": 123}}
    assert persisted_provider_data["ii_agent_secret_sync"] == {
        "revision": "persisted-revision",
        "project_path": "/workspace/app",
    }
    assert persisted_provider_data["template_id"] == "template-1"


@pytest.mark.asyncio
async def test_init_sandbox_reconciles_runtime_secret_state(settings_factory, monkeypatch):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    record = SimpleNamespace(
        id=sandbox_id,
        session_id=session_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={},
    )
    sandbox = SimpleNamespace(
        sandbox_id=str(sandbox_id),
        session_id=str(session_id),
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        metadata={"ii_sandbox_id": str(sandbox_id)},
        files={},
        created_directories=[],
    )

    async def _file_exists(file_path: str) -> bool:
        return file_path in sandbox.files

    async def _read_file(file_path: str) -> str:
        return sandbox.files[file_path]

    async def _write_file(file_path: str, content: str) -> SimpleNamespace:
        sandbox.files[file_path] = content
        return SimpleNamespace(path=file_path)

    async def _create_directory(directory_path: str, exist_ok: bool = False) -> bool:
        sandbox.created_directories.append((directory_path, exist_ok))
        return True

    sandbox.file_exists = _file_exists
    sandbox.read_file = _read_file
    sandbox.write_file = _write_file
    sandbox.create_directory = _create_directory

    sandbox_repo = AsyncMock()
    sandbox_repo.update_provider_info = AsyncMock()
    runtime_state_service = AsyncMock()
    runtime_state_service.get_runtime_state.return_value = SimpleNamespace(
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url="postgres://db.example/app",
    )
    service = SandboxService(
        sandbox_repo=sandbox_repo,
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
        secret_runtime_state_service=runtime_state_service,
    )
    monkeypatch.setattr(service, "_resolve_sandbox_record", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "_connect_provider", AsyncMock(return_value=sandbox))
    monkeypatch.setattr(service, "_configure_mcp", AsyncMock())

    await service.init_sandbox(
        object(),
        session_id=session_id,
        user_id=user_id,
    )

    assert sandbox.created_directories == [("/workspace/app", True)]
    assert sandbox.files["/app/.user_env.sh"] == (
        "# >>> ii-agent managed exports >>>\n"
        "export API_KEY=abc\n"
        "export DATABASE_URL=postgres://db.example/app\n"
        "# <<< ii-agent managed exports <<<\n"
    )
    persisted_provider_data = sandbox_repo.update_provider_info.await_args.kwargs["provider_data"]
    assert persisted_provider_data["ii_agent_secret_sync"]["project_path"] == "/workspace/app"
    assert "revision" in persisted_provider_data["ii_agent_secret_sync"]


@pytest.mark.asyncio
async def test_init_sandbox_recreates_missing_docker_provider_after_local_cleanup(
    settings_factory, monkeypatch
):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    record = SimpleNamespace(
        id=sandbox_id,
        session_id=session_id,
        provider=SandboxProviderType.DOCKER,
        provider_sandbox_id="docker-old",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={"pty_sessions": {"build": {"pid": 123}}},
    )
    sandbox_mgr = SimpleNamespace(
        sandbox_id=str(sandbox_id),
        session_id=str(session_id),
        provider_sandbox_id="docker-new",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        metadata={"ii_sandbox_id": str(sandbox_id), "runtime": "docker"},
    )
    sandbox_repo = AsyncMock()
    sandbox_repo.update_provider_info = AsyncMock()
    service = SandboxService(
        sandbox_repo=sandbox_repo,
        session_repo=FakeSessionRepo({}),
        config=settings_factory(sandbox={"provider": "docker"}),
    )
    monkeypatch.setattr(service, "_resolve_sandbox_record", AsyncMock(return_value=record))
    monkeypatch.setattr(
        service,
        "_connect_provider",
        AsyncMock(side_effect=SandboxNotFoundException("docker-old")),
    )
    monkeypatch.setattr(service, "_create_provider", AsyncMock(return_value=sandbox_mgr))
    monkeypatch.setattr(service, "_configure_mcp", AsyncMock())

    result = await service.init_sandbox(
        object(),
        session_id=session_id,
        user_id=user_id,
    )

    assert result is sandbox_mgr
    service._create_provider.assert_awaited_once_with(record, None)
    service._configure_mcp.assert_awaited_once()
    persisted_provider_data = sandbox_repo.update_provider_info.await_args.kwargs["provider_data"]
    assert persisted_provider_data["pty_sessions"] == {"build": {"pid": 123}}
    assert (
        sandbox_repo.update_provider_info.await_args.kwargs["provider_sandbox_id"] == "docker-new"
    )


@pytest.mark.asyncio
async def test_init_sandbox_reconciles_against_owner_session_for_shared_sandbox(
    settings_factory, monkeypatch
):
    parent_session_id = uuid.uuid4()
    child_session_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    record = SimpleNamespace(
        id=sandbox_id,
        session_id=parent_session_id,
        provider=SandboxProviderType.E2B,
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        provider_data={},
    )
    sandbox = SimpleNamespace(
        sandbox_id=str(sandbox_id),
        session_id=str(parent_session_id),
        provider_sandbox_id="sbx-provider",
        status=SandboxStatus.RUNNING,
        expired_at=None,
        metadata={},
        file_exists=AsyncMock(return_value=False),
        read_file=AsyncMock(return_value=""),
        write_file=AsyncMock(),
        create_directory=AsyncMock(),
    )
    sandbox_repo = AsyncMock()
    sandbox_repo.update_provider_info = AsyncMock()
    runtime_state_service = AsyncMock()
    runtime_state_service.get_runtime_state.return_value = None
    service = SandboxService(
        sandbox_repo=sandbox_repo,
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
        secret_runtime_state_service=runtime_state_service,
    )
    monkeypatch.setattr(service, "_resolve_sandbox_record", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "_connect_provider", AsyncMock(return_value=sandbox))
    monkeypatch.setattr(service, "_configure_mcp", AsyncMock())

    await service.init_sandbox(
        object(),
        session_id=child_session_id,
        user_id=uuid.uuid4(),
    )

    runtime_state_service.get_runtime_state.assert_awaited_once()
    assert (
        runtime_state_service.get_runtime_state.await_args.kwargs["session_id"] == parent_session_id
    )


@pytest.mark.asyncio
async def test_list_shell_sessions_prunes_stale_records(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    live_record = _make_record()
    stale_record = _make_record()
    sandbox, shell = _make_connected_shell(
        monkeypatch,
        service,
        sessions={"build": live_record, "old": stale_record},
    )
    shell.is_session_live = AsyncMock(side_effect=[True, False])

    result = await service.list_shell_sessions(uuid.uuid4())

    assert result == ["build"]
    service.persist_provider_data.assert_awaited_once()
    persisted_provider_data = service.persist_provider_data.await_args.args[1]
    assert list(persisted_provider_data["pty_sessions"]) == ["build"]
    assert str(sandbox.sandbox_id)


@pytest.mark.asyncio
async def test_create_shell_session_persists_record(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record()
    _, shell = _make_connected_shell(monkeypatch, service)
    shell.create_session_record = AsyncMock(return_value=record)
    session_id = uuid.uuid4()

    await service.create_shell_session(
        session_id,
        "build",
        "/workspace/project",
        timeout=42,
    )

    shell.validate_session_name.assert_called_once_with("build")
    shell.normalize_directory.assert_awaited_once_with("/workspace/project")
    shell.create_session_record.assert_awaited_once_with(
        "build",
        "/workspace/project",
        timeout=42,
    )
    persisted_provider_data = service.persist_provider_data.await_args.args[1]
    assert persisted_provider_data["pty_sessions"]["build"] == record.model_dump(mode="json")


@pytest.mark.asyncio
async def test_run_shell_command_uses_service_owned_session_registry(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record()
    _, shell = _make_connected_shell(monkeypatch, service, sessions={"build": record})
    shell.refresh_session_record = AsyncMock(side_effect=[(record, False), (record, False)])
    shell.build_command_request = AsyncMock(
        return_value=ShellExecutionRequest(
            record=record,
            stdin=b"pwd\n",
            log_offset=12,
            expected_prompt_seq=10,
        )
    )
    session_id = uuid.uuid4()

    result = await service.run_shell_command(
        session_id,
        "build",
        "pwd",
        timeout=42,
        wait_for_output=True,
    )

    assert result.clean_output == "ok"
    shell.build_command_request.assert_awaited_once_with(record, "pwd", run_dir=None)
    shell.send_stdin.assert_awaited_once_with("build", record, b"pwd\n")
    shell.wait_for_prompt.assert_awaited_once_with(
        record,
        minimum_prompt_seq=10,
        timeout=42,
    )
    shell.read_command_output.assert_awaited_once_with(record, start_offset=12)


@pytest.mark.asyncio
async def test_delete_shell_session_uses_connected_shell(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record()
    _, shell = _make_connected_shell(monkeypatch, service, sessions={"build": record})
    shell.delete_session = AsyncMock()
    session_id = uuid.uuid4()

    await service.delete_shell_session(session_id, "build")

    shell.delete_session.assert_awaited_once_with("build", record)
    persisted_provider_data = service.persist_provider_data.await_args.args[1]
    assert persisted_provider_data["pty_sessions"] == {}


@pytest.mark.asyncio
async def test_kill_shell_command_uses_connected_shell(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record(status=ShellSessionState.BUSY, pending_prompt_seq=8)
    _, shell = _make_connected_shell(monkeypatch, service, sessions={"build": record})
    shell.build_interrupt_request = AsyncMock(
        return_value=ShellExecutionRequest(
            record=record,
            stdin=b"\x03",
            log_offset=5,
            expected_prompt_seq=8,
        )
    )
    shell.refresh_session_record = AsyncMock(return_value=(record, False))
    session_id = uuid.uuid4()

    result = await service.kill_shell_command(
        session_id,
        "build",
        timeout=42,
    )

    assert result.clean_output == "ok"
    shell.build_interrupt_request.assert_awaited_once_with(record)
    shell.send_stdin.assert_awaited_once_with("build", record, b"\x03")
    shell.wait_for_prompt.assert_awaited_once_with(
        record,
        minimum_prompt_seq=8,
        timeout=42,
    )


@pytest.mark.asyncio
async def test_get_shell_session_output_uses_connected_shell(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record()
    _, shell = _make_connected_shell(monkeypatch, service, sessions={"build": record})
    session_id = uuid.uuid4()

    result = await service.get_shell_session_output(session_id, "build")

    assert result.clean_output == "tail"
    shell.read_session_output.assert_awaited_once_with(record)


@pytest.mark.asyncio
async def test_write_to_shell_process_uses_connected_shell(settings_factory, monkeypatch):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )
    record = _make_record()
    _, shell = _make_connected_shell(monkeypatch, service, sessions={"build": record})
    shell.build_process_input_request = AsyncMock(
        return_value=ShellExecutionRequest(record=record, stdin=b"yes")
    )
    monkeypatch.setattr(
        service,
        "get_shell_session_output",
        AsyncMock(return_value=ShellResult(clean_output="prompt", ansi_output="prompt")),
    )
    session_id = uuid.uuid4()

    result = await service.write_to_shell_process(
        session_id,
        "build",
        "yes",
        press_enter=False,
    )

    assert result.clean_output == "prompt"
    shell.build_process_input_request.assert_awaited_once_with(record, "yes", False)
    shell.send_stdin.assert_awaited_once_with("build", record, b"yes")


@pytest.mark.asyncio
async def test_get_shell_backend_for_session_raises_when_sandbox_missing(
    settings_factory,
    monkeypatch,
):
    service = SandboxService(
        sandbox_repo=FakeSandboxRepo({}),
        session_repo=FakeSessionRepo({}),
        config=settings_factory(),
    )

    monkeypatch.setattr(service, "get_sandbox_for_session", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "ii_agent.agents.sandboxes.service.get_db_session_local",
        lambda: _noop_db_cm(),
    )

    with pytest.raises(ShellOperationError, match="No sandbox found for session"):
        await service.list_shell_sessions(uuid.uuid4())
