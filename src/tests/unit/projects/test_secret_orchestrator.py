from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ii_agent.projects.secrets.env_sync_service import SandboxEnvSyncResult
from ii_agent.projects.secrets.orchestrator import ProjectSecretOrchestrator


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_path="/workspace/demo",
        secrets_json={"encrypted_data": "ignored"},
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_add_secrets_commits_before_existing_sandbox_sync(monkeypatch):
    project = _project()
    secret_service = AsyncMock()
    secret_service.add_secrets.return_value = project

    database_service = AsyncMock()
    database_service.get_project_db_connection.return_value = "postgres://canonical-db"

    env_sync_service = AsyncMock()

    orchestrator = ProjectSecretOrchestrator(
        secret_service=secret_service,
        database_service=database_service,
        env_sync_service=env_sync_service,
    )

    db = SimpleNamespace(commit=AsyncMock())

    import ii_agent.projects.secrets.orchestrator as orchestrator_module

    monkeypatch.setattr(
        orchestrator_module,
        "_decrypt_secrets_payload",
        lambda payload: {"API_KEY": "abc"},
    )

    async def _assert_commit_before_sync(*args, **kwargs):
        assert db.commit.await_count == 1
        assert kwargs["provision_if_missing"] is False
        return SandboxEnvSyncResult(runtime_synced=True)

    env_sync_service.sync_env_files.side_effect = _assert_commit_before_sync

    result = await orchestrator.add_secrets(
        db,
        session_id=uuid4(),
        user_id=uuid4(),
        secrets={"API_KEY": "abc"},
        sync_policy="existing",
    )

    assert result.runtime_synced is True
    assert result.restart_required is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_secrets_uses_ensure_sync_policy_for_runtime_materialization(monkeypatch):
    project = _project()
    secret_service = AsyncMock()
    secret_service.add_secrets.return_value = project

    database_service = AsyncMock()
    database_service.get_project_db_connection.return_value = None
    env_sync_service = AsyncMock()
    env_sync_service.sync_env_files.return_value = SandboxEnvSyncResult(
        runtime_synced=True,
        restart_required=True,
    )

    orchestrator = ProjectSecretOrchestrator(
        secret_service=secret_service,
        database_service=database_service,
        env_sync_service=env_sync_service,
    )

    db = SimpleNamespace(commit=AsyncMock())

    import ii_agent.projects.secrets.orchestrator as orchestrator_module

    monkeypatch.setattr(
        orchestrator_module,
        "_decrypt_secrets_payload",
        lambda payload: {"API_KEY": "abc"},
    )

    session_id = uuid4()
    user_id = uuid4()
    result = await orchestrator.add_secrets(
        db,
        session_id=session_id,
        user_id=user_id,
        secrets={"API_KEY": "abc"},
        sync_policy="ensure",
        project_path="/workspace/custom",
    )

    env_sync_service.sync_env_files.assert_awaited_once_with(
        db,
        session_id=session_id,
        user_id=user_id,
        secrets={"API_KEY": "abc"},
        project_path="/workspace/custom",
        database_url=None,
        provision_if_missing=True,
    )
    assert result.project_path_used == "/workspace/custom"
    assert result.restart_required is True
