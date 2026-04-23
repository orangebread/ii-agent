from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ii_agent.settings.llm.catalog import ANTHROPIC_OAUTH_MODELS, CODEX_OAUTH_MODELS
from ii_agent.settings.llm.service import ModelSettingService
from ii_agent.settings.llm.types import CredentialSource, Provider
from ii_agent.settings.provider_connections.service import ProviderConnectionService


pytestmark = pytest.mark.unit

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")
SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000202")


def _make_setting(
    *,
    setting_id: uuid.UUID | None = None,
    model_id: str,
    user_id: uuid.UUID | None,
    provider: str = Provider.ANTHROPIC.value,
    encrypted_api_key: str | None = "plain-key",
    provider_connection_id: uuid.UUID | None = None,
    config_type: str = "user",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=setting_id or uuid.uuid4(),
        user_id=user_id,
        model_id=model_id,
        provider=provider,
        encrypted_api_key=encrypted_api_key,
        provider_connection_id=provider_connection_id,
        base_url=None,
        display_name=model_id,
        params={
            "max_retries": 3,
            "max_message_chars": 30000,
            "temperature": 0.0,
            "thinking_tokens": 16000,
        },
        pricing=None,
        config_type=config_type,
        is_default=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class FakeDB:
    def __init__(self, repo: FakeRepo) -> None:
        self._repo = repo

    def add(self, setting) -> None:
        if getattr(setting, "id", None) is None:
            setting.id = uuid.uuid4()
        if getattr(setting, "created_at", None) is None:
            setting.created_at = datetime.now(timezone.utc)
        if getattr(setting, "updated_at", None) is None:
            setting.updated_at = datetime.now(timezone.utc)
        self._repo.items[setting.id] = setting

    async def flush(self) -> None:
        return None


class FakeRepo:
    def __init__(self, items: list[SimpleNamespace] | None = None) -> None:
        self.items = {item.id: item for item in items or []}

    async def find_by_model_and_user(self, db, model_id, user_id):
        return next(
            (
                item
                for item in self.items.values()
                if item.model_id == model_id and item.user_id == user_id
            ),
            None,
        )

    async def find_by_id_and_user_id(self, db, setting_id, user_id):
        item = self.items.get(setting_id)
        if item and item.user_id == user_id:
            return item
        return None

    async def find_all_by_user(self, db, user_id, provider=None, config_type=None):
        rows = [item for item in self.items.values() if item.user_id == user_id]
        if provider:
            rows = [item for item in rows if item.provider == provider]
        if config_type:
            rows = [item for item in rows if item.config_type == config_type]
        return rows

    async def find_provider_managed_by_user(self, db, user_id, provider=None):
        rows = [
            item
            for item in self.items.values()
            if item.user_id == user_id and item.provider_connection_id is not None
        ]
        if provider:
            rows = [item for item in rows if item.provider == provider]
        return rows

    async def find_all_system_models(self, db):
        return [item for item in self.items.values() if item.user_id is None]

    async def find_system_model_by_model_id(self, db, model_id):
        return next(
            (
                item
                for item in self.items.values()
                if item.user_id is None and item.model_id == model_id
            ),
            None,
        )

    async def get_by_id(self, db, setting_id):
        return self.items.get(setting_id)

    async def create(self, db, setting):
        if getattr(setting, "id", None) is None:
            setting.id = uuid.uuid4()
        self.items[setting.id] = setting
        return setting

    async def update(self, db, setting):
        self.items[setting.id] = setting
        return setting

    async def delete(self, db, setting):
        self.items.pop(setting.id, None)


class FakeSessionRepo:
    def __init__(self, session) -> None:
        self._session = session

    async def get_by_id(self, db, session_id):
        return self._session


class FakeProviderConnectionRepo:
    def __init__(self) -> None:
        self.by_id = {}
        self.by_key = {}

    async def get_by_id_and_user(self, db, connection_id, user_id):
        row = self.by_id.get(str(connection_id))
        if row and str(row.user_id) == str(user_id):
            return row
        return None

    async def get_by_provider_product(self, db, *, user_id, provider, product):
        return self.by_key.get((str(user_id), provider, product))

    async def create(self, db, row):
        self.by_id[str(row.id)] = row
        self.by_key[(str(row.user_id), row.provider, row.product)] = row
        return row

    async def update(self, db, row):
        self.by_id[str(row.id)] = row
        self.by_key[(str(row.user_id), row.provider, row.product)] = row
        return row


class FakeProviderConnectionService:
    def __init__(self, connection, *, live_credentials=None) -> None:
        self._connection = connection
        self._live_credentials = live_credentials

    async def get_by_provider_product(self, db, *, user_id, provider, product):
        if (
            self._connection.user_id == user_id
            and self._connection.provider == provider
            and self._connection.product == product
        ):
            return self._connection
        return None

    async def get_connection_model(self, db, *, connection_id, user_id):
        if self._connection.id == connection_id and self._connection.user_id == user_id:
            return self._connection
        return None

    def supports_provider_managed_model_catalog(self, connection):
        return True

    def get_live_model_credentials(self, connection):
        return self._live_credentials

    def describe_auth_state(self, connection):
        return SimpleNamespace(needs_reauth=self._live_credentials is None)


@pytest.mark.asyncio
async def test_get_all_available_models_materializes_anthropic_oauth_models(monkeypatch):
    monkeypatch.setattr(
        "ii_agent.settings.llm.service.encryption_manager.decrypt",
        lambda value: value,
    )
    repo = FakeRepo()
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        provider=Provider.ANTHROPIC.value,
        product="claude_code",
        status="connected",
    )
    service = ModelSettingService(
        repo=repo,
        session_repo=FakeSessionRepo(session=None),
        provider_connection_service=FakeProviderConnectionService(
            connection,
            live_credentials=SimpleNamespace(
                api_key=None,
                auth_token="anthropic-live-token",
                base_url=None,
                default_headers=None,
                runtime_product="claude_code",
            ),
        ),
    )

    result = await service.get_all_available_models(
        FakeDB(repo),
        user_id=USER_ID,
    )

    assert len(result.models) == len(ANTHROPIC_OAUTH_MODELS)
    assert all(model.is_selectable for model in result.models)
    assert all(
        model.credential_source == CredentialSource.PROVIDER_OAUTH for model in result.models
    )
    assert all(model.provider_connection_id == connection.id for model in result.models)
    assert all(model.runtime_product == "claude_code" for model in result.models)


@pytest.mark.asyncio
async def test_get_all_available_models_materializes_codex_oauth_models(monkeypatch):
    monkeypatch.setattr(
        "ii_agent.settings.llm.service.encryption_manager.decrypt",
        lambda value: value,
    )
    repo = FakeRepo()
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        provider=Provider.OPENAI.value,
        product="codex",
        status="connected",
        external_account_id="acct-codex",
        connection_metadata={"chatgpt_account_id": "acct-codex"},
    )
    service = ModelSettingService(
        repo=repo,
        session_repo=FakeSessionRepo(session=None),
        provider_connection_service=FakeProviderConnectionService(
            connection,
            live_credentials=SimpleNamespace(
                api_key="codex-access-token",
                auth_token=None,
                base_url="https://chatgpt.com/backend-api/codex",
                default_headers={"ChatGPT-Account-ID": "acct-codex"},
                runtime_product="codex",
            ),
        ),
    )

    result = await service.get_all_available_models(
        FakeDB(repo),
        user_id=USER_ID,
    )

    assert len(result.models) == len(CODEX_OAUTH_MODELS)
    assert all(model.is_selectable for model in result.models)
    assert all(
        model.credential_source == CredentialSource.PROVIDER_OAUTH for model in result.models
    )
    assert all(model.provider_connection_id == connection.id for model in result.models)
    assert all(model.runtime_product == "codex" for model in result.models)


@pytest.mark.asyncio
async def test_get_all_available_models_materializes_codex_oauth_models_from_lowercase_connection(
    monkeypatch,
):
    monkeypatch.setattr(
        "ii_agent.settings.llm.service.encryption_manager.decrypt",
        lambda value: value,
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.encryption_manager.encrypt",
        lambda value: value,
    )
    monkeypatch.setattr(
        "ii_agent.settings.provider_connections.service.encryption_manager.decrypt",
        lambda value: value,
    )
    repo = FakeRepo()
    provider_repo = FakeProviderConnectionRepo()
    provider_connection_service = ProviderConnectionService(repo=provider_repo)
    connection = await provider_connection_service.upsert_connection(
        db=None,
        user_id=USER_ID,
        provider="openai",
        product="codex",
        credentials={
            "tokens": {
                "access_token": "codex-access-token",
                "refresh_token": "codex-refresh-token",
                "account_id": "acct-codex",
            }
        },
        auth_mode="openai_oauth",
        external_account_id="acct-codex",
        display_name="Codex",
        connection_metadata={"chatgpt_account_id": "acct-codex"},
    )
    service = ModelSettingService(
        repo=repo,
        session_repo=FakeSessionRepo(session=None),
        provider_connection_service=provider_connection_service,
    )

    result = await service.get_all_available_models(
        FakeDB(repo),
        user_id=USER_ID,
    )

    assert len(result.models) == len(CODEX_OAUTH_MODELS)
    assert all(model.is_selectable for model in result.models)
    assert all(
        model.credential_source == CredentialSource.PROVIDER_OAUTH for model in result.models
    )
    assert all(model.provider_connection_id == connection.id for model in result.models)
    assert all(model.runtime_product == "codex" for model in result.models)


@pytest.mark.asyncio
async def test_resolve_model_config_prefers_explicit_selection_over_stale_session(monkeypatch):
    monkeypatch.setattr(
        "ii_agent.settings.llm.service.encryption_manager.decrypt",
        lambda value: value,
    )
    stale_setting = _make_setting(
        setting_id=uuid.uuid4(),
        model_id="claude-3-7-sonnet-20250219",
        user_id=USER_ID,
    )
    fresh_setting = _make_setting(
        setting_id=uuid.uuid4(),
        model_id="claude-sonnet-4-5-20250929",
        user_id=USER_ID,
    )
    repo = FakeRepo(items=[stale_setting, fresh_setting])
    service = ModelSettingService(
        repo=repo,
        session_repo=FakeSessionRepo(
            session=SimpleNamespace(id=SESSION_ID, model_setting_id=stale_setting.id)
        ),
    )

    resolved = await service.resolve_model_config(
        db=None,
        session=SimpleNamespace(id=SESSION_ID, user_id=USER_ID),
        source="user",
        model_id=str(fresh_setting.id),
    )

    assert resolved.id == fresh_setting.id
    assert resolved.model_id == fresh_setting.model_id


@pytest.mark.asyncio
async def test_get_user_model_config_resolves_codex_provider_credentials(monkeypatch):
    monkeypatch.setattr(
        "ii_agent.settings.llm.service.encryption_manager.decrypt",
        lambda value: value,
    )
    connection_id = uuid.uuid4()
    setting = _make_setting(
        setting_id=uuid.uuid4(),
        model_id="gpt-5.4",
        user_id=USER_ID,
        provider=Provider.OPENAI.value,
        encrypted_api_key=None,
        provider_connection_id=connection_id,
    )
    repo = FakeRepo(items=[setting])
    connection = SimpleNamespace(
        id=connection_id,
        user_id=USER_ID,
        provider=Provider.OPENAI.value,
        product="codex",
        status="connected",
        external_account_id="acct-codex",
        connection_metadata={"chatgpt_account_id": "acct-codex"},
    )
    service = ModelSettingService(
        repo=repo,
        session_repo=FakeSessionRepo(session=None),
        provider_connection_service=FakeProviderConnectionService(
            connection,
            live_credentials=SimpleNamespace(
                api_key="codex-access-token",
                auth_token=None,
                base_url="https://chatgpt.com/backend-api/codex",
                default_headers={"ChatGPT-Account-ID": "acct-codex"},
                runtime_product="codex",
            ),
        ),
    )

    resolved = await service.get_user_model_config(
        FakeDB(repo),
        setting_id=setting.id,
        user_id=USER_ID,
    )

    assert resolved.model_id == "gpt-5.4"
    assert resolved.runtime_product == "codex"
    assert resolved.base_url == "https://chatgpt.com/backend-api/codex"
    assert resolved.default_headers == {"ChatGPT-Account-ID": "acct-codex"}
    assert resolved.api_key is not None
    assert resolved.api_key.get_secret_value() == "codex-access-token"
    assert resolved.auth_token is None
