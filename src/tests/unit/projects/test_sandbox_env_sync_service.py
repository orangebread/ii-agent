from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ii_agent.core.exceptions import ValidationError
from ii_agent.projects.secrets.env_sync_service import SandboxEnvSyncService


class _FakeSandbox:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.sandbox_id = str(uuid.uuid4())
        self.files = files or {}
        self.created_directories: list[tuple[str, bool]] = []
        self.writes: list[tuple[str, str]] = []

    async def file_exists(self, file_path: str) -> bool:
        return file_path in self.files

    async def read_file(self, file_path: str) -> str:
        return self.files[file_path]

    async def write_file(self, file_path: str, content: str) -> SimpleNamespace:
        self.files[file_path] = content
        self.writes.append((file_path, content))
        return SimpleNamespace(path=file_path)

    async def create_directory(self, directory_path: str, exist_ok: bool = False) -> bool:
        self.created_directories.append((directory_path, exist_ok))
        return True


@pytest.mark.asyncio
async def test_sync_env_files_writes_managed_blocks_and_preserves_unmanaged_content():
    sandbox = _FakeSandbox(
        files={
            "/workspace/app/.env": "EXISTING=1\n",
            "/app/.user_env.sh": "export OTHER=1\n",
        }
    )
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {}

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "abc 123"},
        project_path="/workspace/app",
        database_url="postgres://db.example/app",
    )

    assert result.runtime_synced is True
    assert result.restart_required is False
    assert sandbox.created_directories == [("/workspace/app", True)]
    sandbox_service.persist_provider_data.assert_awaited_once()
    assert sandbox.files["/workspace/app/.env"] == (
        "EXISTING=1\n\n"
        "# >>> ii-agent managed secrets >>>\n"
        'API_KEY="abc 123"\n'
        "DATABASE_URL=postgres://db.example/app\n"
        "# <<< ii-agent managed secrets <<<\n"
    )
    assert sandbox.files["/app/.user_env.sh"] == (
        "export OTHER=1\n\n"
        "# >>> ii-agent managed exports >>>\n"
        "export API_KEY='abc 123'\n"
        "export DATABASE_URL=postgres://db.example/app\n"
        "# <<< ii-agent managed exports <<<\n"
    )


@pytest.mark.asyncio
async def test_sync_env_files_replaces_existing_managed_block_and_removes_deleted_keys():
    sandbox = _FakeSandbox(
        files={
            "/workspace/app/.env": (
                "EXISTING=1\n\n"
                "# >>> ii-agent managed secrets >>>\n"
                "OLD_KEY=old\n"
                "DATABASE_URL=postgres://old\n"
                "# <<< ii-agent managed secrets <<<\n"
            ),
            "/app/.user_env.sh": (
                "export OTHER=1\n\n"
                "# >>> ii-agent managed exports >>>\n"
                "export OLD_KEY=old\n"
                "export DATABASE_URL=postgres://old\n"
                "# <<< ii-agent managed exports <<<\n"
            ),
        }
    )
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {}

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"NEW_KEY": "new"},
        project_path="/workspace/app",
        database_url=None,
    )

    assert result.runtime_synced is True
    assert "OLD_KEY" not in sandbox.files["/workspace/app/.env"]
    assert "OLD_KEY" not in sandbox.files["/app/.user_env.sh"]
    assert "DATABASE_URL" not in sandbox.files["/workspace/app/.env"]
    assert "DATABASE_URL" not in sandbox.files["/app/.user_env.sh"]
    assert sandbox.files["/workspace/app/.env"] == (
        "EXISTING=1\n\n"
        "# >>> ii-agent managed secrets >>>\n"
        "NEW_KEY=new\n"
        "# <<< ii-agent managed secrets <<<\n"
    )
    assert sandbox.files["/app/.user_env.sh"] == (
        "export OTHER=1\n\n"
        "# >>> ii-agent managed exports >>>\n"
        "export NEW_KEY=new\n"
        "# <<< ii-agent managed exports <<<\n"
    )


@pytest.mark.asyncio
async def test_sync_env_files_initializes_sandbox_when_needed():
    sandbox = _FakeSandbox()
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {}

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url=None,
    )

    assert result.runtime_synced is True
    sandbox_service.get_sandbox_by_session.assert_awaited_once()
    assert sandbox.files["/app/.user_env.sh"] == (
        "# >>> ii-agent managed exports >>>\n"
        "export API_KEY=abc\n"
        "# <<< ii-agent managed exports <<<\n"
    )


@pytest.mark.asyncio
async def test_sync_env_files_skips_when_existing_sandbox_required_but_missing():
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_for_session.return_value = None

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url=None,
        provision_if_missing=False,
    )

    assert result.runtime_synced is False
    assert result.restart_required is False
    sandbox_service.get_sandbox_for_session.assert_awaited_once()
    sandbox_service.get_sandbox_by_session.assert_not_called()


@pytest.mark.asyncio
async def test_sync_env_files_skips_invalid_legacy_keys():
    sandbox = _FakeSandbox()
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {}

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={
            "GOOD_KEY": "good",
            "BAD-KEY": "bad",
            "ALSO\nBAD": "bad",
        },
        project_path="/workspace/app",
        database_url=None,
    )

    assert result.runtime_synced is True
    assert "GOOD_KEY=good" in sandbox.files["/workspace/app/.env"]
    assert "BAD-KEY" not in sandbox.files["/workspace/app/.env"]
    assert "ALSO\nBAD" not in sandbox.files["/workspace/app/.env"]
    assert "export GOOD_KEY=good" in sandbox.files["/app/.user_env.sh"]
    assert "BAD-KEY" not in sandbox.files["/app/.user_env.sh"]


@pytest.mark.asyncio
async def test_sync_env_files_rejects_project_path_outside_workspace():
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = _FakeSandbox()

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    with pytest.raises(ValidationError, match="sandbox workspace"):
        await service.sync_env_files(
            None,
            session_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            secrets={"API_KEY": "abc"},
            project_path="../../app",
            database_url=None,
        )

    sandbox_service.get_sandbox_by_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_env_files_skips_rewrite_when_revision_is_current():
    sandbox = _FakeSandbox(
        files={
            "/workspace/app/.env": "EXISTING=1\n",
            "/app/.user_env.sh": "export OTHER=1\n",
        }
    )
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)
    target_state = service.build_target_state(
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url=None,
    )
    sandbox_service.load_provider_data.return_value = service.attach_sync_metadata({}, target_state)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url=None,
    )

    assert result.runtime_synced is True
    assert result.restart_required is False
    assert sandbox.writes == []
    sandbox_service.persist_provider_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_env_files_cleans_previous_managed_dotenv_when_project_path_changes():
    sandbox = _FakeSandbox(
        files={
            "/workspace/old/.env": (
                "EXISTING=1\n\n"
                "# >>> ii-agent managed secrets >>>\n"
                "API_KEY=old\n"
                "# <<< ii-agent managed secrets <<<\n"
            ),
            "/app/.user_env.sh": (
                "# >>> ii-agent managed exports >>>\n"
                "export API_KEY=old\n"
                "# <<< ii-agent managed exports <<<\n"
            ),
        }
    )
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {
        "ii_agent_secret_sync": {
            "revision": "old-revision",
            "project_path": "/workspace/old",
        }
    }

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "new"},
        project_path="/workspace/new",
        database_url=None,
    )

    assert result.runtime_synced is True
    assert sandbox.files["/workspace/old/.env"] == "EXISTING=1\n"
    assert sandbox.files["/workspace/new/.env"] == (
        "# >>> ii-agent managed secrets >>>\nAPI_KEY=new\n# <<< ii-agent managed secrets <<<\n"
    )
    assert sandbox.created_directories == [("/workspace/new", True)]


@pytest.mark.asyncio
async def test_sync_env_files_flags_restart_when_live_terminal_exists():
    sandbox = _FakeSandbox()
    sandbox_service = AsyncMock()
    sandbox_service.get_sandbox_by_session.return_value = sandbox
    sandbox_service.load_provider_data.return_value = {
        "pty_sessions": {"sid-1": {"terminal_id": "term-1"}},
    }

    service = SandboxEnvSyncService(sandbox_service=sandbox_service)

    result = await service.sync_env_files(
        None,
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        secrets={"API_KEY": "abc"},
        project_path="/workspace/app",
        database_url=None,
    )

    assert result.runtime_synced is True
    assert result.restart_required is True
