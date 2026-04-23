import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ii_agent.core.exceptions import ValidationError
import ii_agent.projects.secrets.service as secret_service_module
from ii_agent.projects.secrets.service import SecretService


@pytest.mark.asyncio
async def test_replace_session_project_secrets_encrypts_and_persists(settings_factory, monkeypatch):
    project_repo = AsyncMock()
    project = SimpleNamespace(secrets_json=None)

    project_repo.get_by_session_and_user.return_value = project

    async def _update(db, item):
        return item

    project_repo.update.side_effect = _update

    monkeypatch.setattr(
        secret_service_module,
        "_encrypt_secrets_payload",
        lambda payload: {"encrypted_data": f"enc:{payload['API_KEY']}"},
    )

    service = SecretService(project_repo=project_repo, config=settings_factory())

    updated = await service.replace_session_project_secrets(
        db=None,
        session_id="session-1",
        user_id="user-1",
        secrets={"API_KEY": "secret-123"},
    )

    assert updated.secrets_json == {"encrypted_data": "enc:secret-123"}
    project_repo.update.assert_awaited_once_with(None, project)


@pytest.mark.asyncio
async def test_add_and_delete_secrets_apply_merge_semantics(settings_factory, monkeypatch):
    project_repo = AsyncMock()
    project_repo.get_by_session_and_user.return_value = SimpleNamespace(
        secrets_json={"encrypted_data": "ignored"}
    )

    monkeypatch.setattr(
        secret_service_module,
        "_decrypt_secrets_payload",
        lambda payload: {"A": "1", "B": "2", "BAD-NAME": "legacy"},
    )

    service = SecretService(project_repo=project_repo, config=settings_factory())
    service.replace_session_project_secrets = AsyncMock(
        return_value=SimpleNamespace(id="project-1")
    )

    session_id = uuid.uuid4()

    await service.add_secrets(
        db=None,
        session_id=session_id,
        user_id="user-1",
        secrets={"B": "9", "C": "3"},
    )
    add_call = service.replace_session_project_secrets.await_args
    assert add_call.kwargs["secrets"] == {"A": "1", "B": "9", "C": "3"}

    service.replace_session_project_secrets.reset_mock()

    await service.delete_secrets(
        db=None,
        session_id=session_id,
        user_id="user-1",
        secret_keys=["B", "missing", "BAD-NAME"],
    )
    delete_call = service.replace_session_project_secrets.await_args
    assert delete_call.kwargs["secrets"] == {"A": "1"}


@pytest.mark.asyncio
async def test_add_and_delete_secrets_fallback_when_decrypt_is_not_dict(
    settings_factory, monkeypatch
):
    project_repo = AsyncMock()
    project_repo.get_by_session_and_user.return_value = SimpleNamespace(
        secrets_json={"encrypted_data": "ignored"}
    )

    monkeypatch.setattr(secret_service_module, "_decrypt_secrets_payload", lambda payload: ["bad"])

    service = SecretService(project_repo=project_repo, config=settings_factory())
    service.replace_session_project_secrets = AsyncMock(
        return_value=SimpleNamespace(id="project-1")
    )

    session_id = uuid.uuid4()

    await service.add_secrets(
        db=None,
        session_id=session_id,
        user_id="user-1",
        secrets={"X": "1"},
    )
    add_call = service.replace_session_project_secrets.await_args
    assert add_call.kwargs["secrets"] == {"X": "1"}

    service.replace_session_project_secrets.reset_mock()

    await service.delete_secrets(
        db=None,
        session_id=session_id,
        user_id="user-1",
        secret_keys=["X"],
    )
    delete_call = service.replace_session_project_secrets.await_args
    assert delete_call.kwargs["secrets"] == {}


@pytest.mark.asyncio
async def test_replace_session_project_secrets_rejects_invalid_env_var_names(settings_factory):
    service = SecretService(project_repo=AsyncMock(), config=settings_factory())

    with pytest.raises(ValidationError, match="Invalid environment variable"):
        await service.replace_session_project_secrets(
            db=None,
            session_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            secrets={"BAD-NAME": "secret-123"},
        )
