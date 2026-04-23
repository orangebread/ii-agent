from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ii_agent.projects.secrets.runtime_state import ProjectSecretRuntimeStateService


@pytest.mark.asyncio
async def test_get_runtime_state_returns_canonical_database_url_and_sanitized_secrets(monkeypatch):
    session_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    project_repo = AsyncMock()
    project_repo.get_by_session_and_user.return_value = SimpleNamespace(
        id=project_id,
        project_path="/workspace/demo",
        secrets_json={"encrypted_data": "ignored"},
    )
    database_service = AsyncMock()
    database_service.get_project_db_connection.return_value = "postgres://canonical-db"

    service = ProjectSecretRuntimeStateService(
        project_repo=project_repo,
        database_service=database_service,
    )

    import ii_agent.projects.secrets.runtime_state as runtime_state_module

    monkeypatch.setattr(
        runtime_state_module,
        "_decrypt_secrets_payload",
        lambda payload: {
            "GOOD_KEY": "good",
            "BAD-KEY": "bad",
        },
    )

    state = await service.get_runtime_state(
        None,
        session_id=session_id,
        user_id=user_id,
    )

    assert state is not None
    assert state.project_id == project_id
    assert state.project_path == "/workspace/demo"
    assert state.secrets == {"GOOD_KEY": "good"}
    assert state.database_url == "postgres://canonical-db"


@pytest.mark.asyncio
async def test_get_runtime_state_returns_none_without_project():
    project_repo = AsyncMock()
    project_repo.get_by_session_and_user.return_value = None
    database_service = AsyncMock()

    service = ProjectSecretRuntimeStateService(
        project_repo=project_repo,
        database_service=database_service,
    )

    state = await service.get_runtime_state(
        None,
        session_id=uuid4(),
        user_id=uuid4(),
    )

    assert state is None
    database_service.get_project_db_connection.assert_not_awaited()
