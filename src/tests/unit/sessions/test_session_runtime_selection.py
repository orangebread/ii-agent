from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ii_agent.sessions.service import SessionService
from ii_agent.settings.llm.schemas import ModelConfig
from ii_agent.settings.llm.types import ConfigType, CredentialSource, Provider


class FakeSessionRepo:
    def __init__(self, session) -> None:
        self._session = session

    async def get_by_id_with_project(self, db, session_id):
        return self._session

    async def get_by_id(self, db, session_id):
        return self._session


class FakeCache:
    async def evict(self, key: str) -> None:
        return None


class FakeCreditService:
    async def has_sufficient_credits(self, db, user_id, required):
        return True


def _make_service(session) -> SessionService:
    return SessionService(
        session_repo=FakeSessionRepo(session),
        event_repo=SimpleNamespace(),
        run_task_service=SimpleNamespace(),
        file_store=SimpleNamespace(),
        file_service=SimpleNamespace(),
        sandbox_repo=SimpleNamespace(),
        cache=FakeCache(),
        config=SimpleNamespace(workspace_path="/tmp/workspace"),
    )


def _make_session(session_id: uuid.UUID, user_id: uuid.UUID):
    session = SimpleNamespace(
        id=session_id,
        user_id=user_id,
        name=None,
        status="active",
        agent_type=None,
        app_kind="agent",
        is_public=False,
        public_url=None,
        api_version="v0",
        session_metadata={},
        last_message_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        model_setting_id=None,
        mcp_setting_id=None,
        project=None,
    )
    session.get_workspace_dir = lambda: f"/tmp/workspace/{session_id}"
    return session


@pytest.mark.asyncio
async def test_validate_and_prepare_for_run_syncs_runtime_to_selected_provider_model():
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    model_setting_id = uuid.uuid4()
    runtime_setting_id = uuid.uuid4()
    provider_connection_id = uuid.uuid4()
    session = _make_session(session_id, user_id)
    service = _make_service(session)
    db = SimpleNamespace(flush=lambda: None)
    db.flush = lambda: None

    async def _flush():
        return None

    db.flush = _flush

    model_setting_service = SimpleNamespace(
        resolve_model_config=lambda *args, **kwargs: None,
    )
    model_config = ModelConfig(
        id=model_setting_id,
        model_id="gpt-5.4",
        provider=Provider.OPENAI,
        provider_connection_id=provider_connection_id,
        runtime_product="codex",
        config_type=ConfigType.USER,
        credential_source=CredentialSource.PROVIDER_OAUTH,
    )

    async def _resolve_model_config(*args, **kwargs):
        return model_config

    model_setting_service.resolve_model_config = _resolve_model_config

    mcp_setting_service = SimpleNamespace(
        resolve_runtime_setting_for_run=lambda *args, **kwargs: None,
    )

    async def _resolve_runtime_setting_for_run(*args, **kwargs):
        return SimpleNamespace(id=runtime_setting_id)

    mcp_setting_service.resolve_runtime_setting_for_run = _resolve_runtime_setting_for_run

    with patch("ii_agent.sessions.service.sa_inspect") as mock_inspect:
        mock_state = MagicMock()
        mock_state.unloaded = {"project"}
        mock_inspect.return_value = mock_state

        result = await service.validate_and_prepare_for_run(
            db,
            session_id=session_id,
            user_id=user_id,
            source="user",
            model_id=str(model_setting_id),
            text="Use Codex for this run",
            agent_type="codex",
            credit_service=FakeCreditService(),
            model_setting_service=model_setting_service,
            mcp_setting_service=mcp_setting_service,
        )

    assert result.is_valid is True
    assert session.model_setting_id == model_setting_id
    assert session.mcp_setting_id == runtime_setting_id
    assert session.agent_type == "codex"
