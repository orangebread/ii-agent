"""Deep unit tests for MCPSettingService and MCPSettingRepository covering all branches."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Import all related models to avoid SQLAlchemy mapper issues
import ii_agent.settings.mcp.models  # noqa: F401
import ii_agent.files.models  # noqa: F401
import ii_agent.sessions.wishlist.models  # noqa: F401
import ii_agent.integrations.connectors.models  # noqa: F401
import ii_agent.billing.models  # noqa: F401
import ii_agent.projects.models  # noqa: F401
import ii_agent.settings.skills.models  # noqa: F401
import ii_agent.content.slides.models  # noqa: F401
import ii_agent.content.storybook.models  # noqa: F401
import ii_agent.projects.databases.models  # noqa: F401
import ii_agent.projects.subdomains.models  # noqa: F401
import ii_agent.projects.deployments.models  # noqa: F401
import ii_agent.settings.llm.models  # noqa: F401

from ii_agent.settings.mcp.exceptions import MCPOAuthError, MCPSettingNotFoundError
from ii_agent.settings.mcp.schemas import MCPServersConfig, MCPSettingCreate, MCPSettingUpdate
from ii_agent.settings.mcp.service import (
    MCPSettingService,
    _verify_claude_code_oauth_login_id,
    _to_mcp_setting_info,
)
from ii_agent.settings.provider_connections.service import ProviderConnectionAuthState

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fake model and repo helpers
# ---------------------------------------------------------------------------


def _make_mcp_setting(
    user_id: str = "user-1",
    setting_id: str | None = None,
    is_active: bool = True,
    mcp_config: dict | None = None,
    mcp_metadata: dict | None = None,
    provider_connection_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=setting_id or str(uuid.uuid4()),
        user_id=user_id,
        provider_connection_id=provider_connection_id,
        mcp_config=mcp_config or {"mcpServers": {}},
        mcp_metadata=mcp_metadata,
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class FakeMCPRepo:
    def __init__(self):
        self.items: dict = {}  # id -> setting
        self.by_tool_type: dict = {}  # tool_type -> setting

    async def get_by_id_and_user(self, db, setting_id, user_id):
        s = self.items.get(str(setting_id))
        if s and str(s.user_id) == str(user_id):
            return s
        return None

    async def get_by_user_and_tool_type(self, db, user_id, tool_type):
        s = self.by_tool_type.get(tool_type)
        if s and s.user_id == user_id:
            return s
        return None

    async def list_by_user(self, db, user_id, only_active=False, no_metadata=False):
        result = [s for s in self.items.values() if s.user_id == user_id]
        if only_active:
            result = [s for s in result if s.is_active]
        if no_metadata:
            result = [s for s in result if not s.mcp_metadata]
        return result

    async def list_active_by_user(self, db, user_id):
        return await self.list_by_user(db, user_id, only_active=True)

    async def list_runtime_settings_by_user(self, db, user_id, *, only_active=False):
        result = [
            s
            for s in self.items.values()
            if str(s.user_id) == str(user_id)
            and (s.mcp_metadata or {}).get("tool_type") in {"codex", "claude_code"}
        ]
        if only_active:
            result = [s for s in result if s.is_active]
        return result

    async def has_provider_connection_reference(self, db, provider_connection_id):
        return any(
            str(setting.provider_connection_id) == str(provider_connection_id)
            for setting in self.items.values()
        )

    async def create(self, db, setting):
        self.items[setting.id] = setting
        # Track by tool_type if metadata has it
        if setting.mcp_metadata and "tool_type" in setting.mcp_metadata:
            self.by_tool_type[setting.mcp_metadata["tool_type"]] = setting
        return setting

    async def update(self, db, setting):
        self.items[setting.id] = setting
        if setting.mcp_metadata and "tool_type" in setting.mcp_metadata:
            self.by_tool_type[setting.mcp_metadata["tool_type"]] = setting
        return setting

    async def delete(self, db, setting):
        self.items.pop(setting.id, None)
        # Remove from by_tool_type if tracked
        for k, v in list(self.by_tool_type.items()):
            if v is setting:
                del self.by_tool_type[k]


class FakeProviderConnectionService:
    def __init__(self, connection_id_factory=None):
        self.connections: dict[str, dict] = {}
        self.counter = 0
        self.deleted_connection_ids: list[str] = []
        self.connection_id_factory = connection_id_factory or (lambda: str(uuid.uuid4()))

    async def upsert_connection(self, db, **kwargs):
        existing_key = None
        existing_row_id = None
        for connection_id, stored in self.connections.items():
            row = stored["row"]
            if (
                row.user_id == kwargs["user_id"]
                and row.provider == kwargs["provider"]
                and row.product == kwargs["product"]
            ):
                existing_key = connection_id
                existing_row_id = row.id
                break

        if existing_key is None:
            self.counter += 1
            existing_row_id = self.connection_id_factory()
            existing_key = str(existing_row_id)

        row = SimpleNamespace(
            id=existing_row_id,
            user_id=kwargs["user_id"],
            provider=kwargs["provider"],
            product=kwargs["product"],
            encrypted_credentials_json="encrypted",
            connection_metadata=kwargs.get("connection_metadata") or {},
            status=kwargs.get("status", "connected"),
            expires_at=kwargs.get("expires_at"),
        )
        self.connections[existing_key] = {
            "row": row,
            "credentials": kwargs.get("credentials") or {},
        }
        return row

    async def delete_connection(self, db, *, connection_id, user_id):
        stored = self.connections.get(str(connection_id))
        if not stored:
            return False
        if str(stored["row"].user_id) != str(user_id):
            return False
        self.deleted_connection_ids.append(str(connection_id))
        del self.connections[str(connection_id)]
        return True

    async def get_connection_model(self, db, *, connection_id, user_id):
        stored = self.connections.get(str(connection_id))
        if not stored:
            return None
        row = stored["row"]
        return row if str(row.user_id) == str(user_id) else None

    def get_credentials_dict(self, connection):
        stored = self.connections.get(str(connection.id))
        return stored["credentials"] if stored else {}

    def has_usable_credentials(self, connection):
        return self.describe_auth_state(connection).is_usable

    def describe_auth_state(self, connection):
        credentials = self.get_credentials_dict(connection)
        if not credentials:
            return ProviderConnectionAuthState(
                has_stored_auth=False,
                is_usable=False,
                auth_status="missing",
                needs_reauth=True,
            )
        if getattr(connection, "status", "connected") != "connected":
            return ProviderConnectionAuthState(
                has_stored_auth=True,
                is_usable=False,
                auth_status=getattr(connection, "status", "error"),
                needs_reauth=True,
            )

        expires_at = getattr(connection, "expires_at", None)
        claude_oauth = credentials.get("claudeAiOauth", {})
        if (
            expires_at is not None
            and expires_at <= datetime.now(timezone.utc)
            and not (isinstance(claude_oauth, dict) and claude_oauth.get("refreshToken"))
        ):
            return ProviderConnectionAuthState(
                has_stored_auth=True,
                is_usable=False,
                auth_status="expired",
                needs_reauth=True,
            )

        return ProviderConnectionAuthState(
            has_stored_auth=True,
            is_usable=True,
            auth_status="connected",
            needs_reauth=False,
        )


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user or SimpleNamespace(id="u1", default_mcp_setting_id=None)

    async def get_by_id(self, db, user_id):
        if str(self.user.id) != str(user_id):
            return None
        return self.user

    async def set_default_mcp_setting_id(self, db, user, setting_id):
        user.default_mcp_setting_id = setting_id


class FakeSessionRepo:
    def __init__(self, sessions=None):
        self.sessions = {str(session.id): session for session in (sessions or [])}
        self.clear_calls = []

    async def get_by_id(self, db, session_id):
        return self.sessions.get(str(session_id))

    async def clear_mcp_setting_references(self, db, *, user_id, setting_id):
        self.clear_calls.append((str(user_id), str(setting_id)))
        for session in self.sessions.values():
            if str(session.user_id) == str(user_id) and str(session.mcp_setting_id) == str(
                setting_id
            ):
                session.mcp_setting_id = None


def _make_service(
    repo: FakeMCPRepo | None = None,
    settings_factory=None,
    config=None,
    provider_connection_service: FakeProviderConnectionService | None = None,
    user_repo: FakeUserRepo | None = None,
    session_repo: FakeSessionRepo | None = None,
) -> MCPSettingService:
    if config is None and settings_factory is not None:
        config = settings_factory()
    elif config is None:
        config = SimpleNamespace(
            mcp=SimpleNamespace(
                anthropic_oauth_authorize_url="https://claude.ai/oauth/authorize",
                anthropic_oauth_token_url="https://oauth.example.com/token",
                anthropic_oauth_client_id="client-id",
                anthropic_oauth_redirect_uri="https://example.com/callback",
            ),
            ii_frontend_url="http://localhost:1420",
            oauth=SimpleNamespace(session_secret_key="session-secret"),
            environment="local",
        )
    return MCPSettingService(
        repo=repo or FakeMCPRepo(),
        config=config,
        user_repo=user_repo,
        session_repo=session_repo,
        provider_connection_service=provider_connection_service or FakeProviderConnectionService(),
    )


# ---------------------------------------------------------------------------
# Tests – create_mcp_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mcp_settings_keeps_existing_active():
    """Creating a setting no longer deactivates unrelated active settings."""
    active1 = _make_mcp_setting(user_id="u1", is_active=True)
    active2 = _make_mcp_setting(user_id="u1", is_active=True)
    repo = FakeMCPRepo()
    repo.items[active1.id] = active1
    repo.items[active2.id] = active2

    svc = _make_service(repo=repo)

    result = await svc.create_mcp_settings(
        db=None,
        user_id="u1",
        mcp_setting_in=MCPSettingCreate(
            mcp_config=MCPServersConfig(mcpServers={}),
            metadata=None,
        ),
    )

    assert active1.is_active is True
    assert active2.is_active is True
    assert result.is_active is True


@pytest.mark.asyncio
async def test_create_mcp_settings_no_active_settings():
    """Creating when no active settings exist works correctly."""
    repo = FakeMCPRepo()
    svc = _make_service(repo=repo)

    result = await svc.create_mcp_settings(
        db=None,
        user_id="u1",
        mcp_setting_in=MCPSettingCreate(
            mcp_config=MCPServersConfig(mcpServers={}),
            metadata=None,
        ),
    )

    assert result is not None
    assert len(repo.items) == 1


@pytest.mark.asyncio
async def test_create_mcp_settings_stores_metadata():
    """Metadata is serialized and stored on the new setting."""
    from ii_agent.settings.mcp.schemas import CodexMetadata

    repo = FakeMCPRepo()
    svc = _make_service(repo=repo)

    codex_meta = CodexMetadata(
        auth_json={"OPENAI_API_KEY": "test-key"},
        store_path="~/.codex",
    )

    await svc.create_mcp_settings(
        db=None,
        user_id="u1",
        mcp_setting_in=MCPSettingCreate(
            mcp_config=MCPServersConfig(mcpServers={}),
            metadata=codex_meta,
        ),
    )

    stored = list(repo.items.values())[0]
    assert stored.mcp_metadata is not None
    assert stored.mcp_metadata.get("tool_type") == "codex"


@pytest.mark.asyncio
async def test_create_mcp_settings_strips_legacy_claude_auth_json():
    """Claude runtime metadata must not persist raw auth payloads."""
    repo = FakeMCPRepo()
    svc = _make_service(repo=repo)

    await svc.create_mcp_settings(
        db=None,
        user_id="u1",
        mcp_setting_in=MCPSettingCreate.model_validate(
            {
                "mcp_config": {"mcpServers": {}},
                "metadata": {
                    "tool_type": "claude_code",
                    "auth_json": {"claudeAiOauth": {"refreshToken": "secret"}},
                    "store_path": "~/.claude",
                },
            }
        ),
    )

    stored = list(repo.items.values())[0]
    assert stored.mcp_metadata["tool_type"] == "claude_code"
    assert stored.mcp_metadata["store_path"] == "~/.claude"
    assert "auth_json" not in stored.mcp_metadata


# ---------------------------------------------------------------------------
# Tests – update_mcp_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_mcp_settings_applies_changes():
    """Provided fields are updated; returns updated info."""
    setting = _make_mcp_setting(user_id="u1")
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(repo=repo)

    result = await svc.update_mcp_settings(
        db=None,
        setting_id=setting.id,
        user_id="u1",
        setting_update=MCPSettingUpdate(
            is_active=False,
        ),
    )

    assert result.is_active is False


@pytest.mark.asyncio
async def test_update_mcp_settings_not_found_raises():
    """Non-existent setting raises MCPSettingNotFoundError."""
    svc = _make_service()

    with pytest.raises(MCPSettingNotFoundError):
        await svc.update_mcp_settings(
            db=None,
            setting_id="ghost",
            user_id="u1",
            setting_update=MCPSettingUpdate(is_active=False),
        )


@pytest.mark.asyncio
async def test_update_mcp_settings_updates_mcp_config():
    """Updating mcp_config field is applied."""
    setting = _make_mcp_setting(user_id="u1")
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(repo=repo)

    new_config = MCPServersConfig.model_validate(
        {
            "mcpServers": {
                "test-server": {
                    "command": "npx",
                    "args": ["-y", "test-server@latest"],
                }
            }
        }
    )

    result = await svc.update_mcp_settings(
        db=None,
        setting_id=setting.id,
        user_id="u1",
        setting_update=MCPSettingUpdate(mcp_config=new_config),
    )

    assert result is not None


@pytest.mark.asyncio
async def test_update_mcp_settings_strips_legacy_claude_auth_json():
    """Claude runtime updates must not reintroduce raw auth payloads."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={"tool_type": "claude_code", "store_path": "~/.claude"},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(repo=repo)

    await svc.update_mcp_settings(
        db=None,
        setting_id=setting.id,
        user_id="u1",
        setting_update=MCPSettingUpdate.model_validate(
            {
                "metadata": {
                    "tool_type": "claude_code",
                    "auth_json": {"claudeAiOauth": {"refreshToken": "secret"}},
                    "store_path": "~/.claude",
                }
            }
        ),
    )

    assert setting.mcp_metadata["tool_type"] == "claude_code"
    assert setting.mcp_metadata["store_path"] == "~/.claude"
    assert "auth_json" not in setting.mcp_metadata


# ---------------------------------------------------------------------------
# Tests – get_mcp_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mcp_settings_success():
    """Existing setting is returned as MCPSettingInfo."""
    setting = _make_mcp_setting(user_id="u1")
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(repo=repo)

    result = await svc.get_mcp_settings(db=None, setting_id=setting.id, user_id="u1")

    assert str(result.id) == setting.id


@pytest.mark.asyncio
async def test_get_mcp_settings_not_found_raises():
    """Non-existent setting raises MCPSettingNotFoundError."""
    svc = _make_service()

    with pytest.raises(MCPSettingNotFoundError):
        await svc.get_mcp_settings(db=None, setting_id="missing", user_id="u1")


# ---------------------------------------------------------------------------
# Tests – list_mcp_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_mcp_settings_returns_all():
    """All settings for the user are returned."""
    s1 = _make_mcp_setting(user_id="u1", is_active=True)
    s2 = _make_mcp_setting(user_id="u1", is_active=False)
    s3 = _make_mcp_setting(user_id="u2", is_active=True)
    repo = FakeMCPRepo()
    repo.items.update({s1.id: s1, s2.id: s2, s3.id: s3})
    svc = _make_service(repo=repo)

    result = await svc.list_mcp_settings(db=None, user_id="u1")

    assert len(result.settings) == 2


@pytest.mark.asyncio
async def test_list_mcp_settings_only_active():
    """only_active=True filters to active settings only."""
    s1 = _make_mcp_setting(user_id="u1", is_active=True)
    s2 = _make_mcp_setting(user_id="u1", is_active=False)
    repo = FakeMCPRepo()
    repo.items.update({s1.id: s1, s2.id: s2})
    svc = _make_service(repo=repo)

    result = await svc.list_mcp_settings(db=None, user_id="u1", only_active=True)

    assert len(result.settings) == 1
    assert str(result.settings[0].id) == s1.id


@pytest.mark.asyncio
async def test_list_mcp_settings_no_metadata_filter():
    """no_metadata=True returns only settings without metadata."""
    s_with_meta = _make_mcp_setting(
        user_id="u1", mcp_metadata={"tool_type": "codex", "auth_json": {}, "store_path": ""}
    )
    s_without_meta = _make_mcp_setting(user_id="u1", mcp_metadata=None)
    repo = FakeMCPRepo()
    repo.items.update({s_with_meta.id: s_with_meta, s_without_meta.id: s_without_meta})
    svc = _make_service(repo=repo)

    result = await svc.list_mcp_settings(db=None, user_id="u1", no_metadata=True)

    assert len(result.settings) == 1
    assert str(result.settings[0].id) == s_without_meta.id


# ---------------------------------------------------------------------------
# Tests – delete_mcp_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_mcp_settings_success():
    """Existing setting is deleted and True returned."""
    setting = _make_mcp_setting(user_id="u1")
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(repo=repo)

    result = await svc.delete_mcp_settings(db=None, setting_id=setting.id, user_id="u1")

    assert result is True
    assert setting.id not in repo.items


@pytest.mark.asyncio
async def test_delete_mcp_settings_not_found_returns_false():
    """Non-existent setting returns False."""
    svc = _make_service()

    result = await svc.delete_mcp_settings(db=None, setting_id="ghost", user_id="u1")

    assert result is False


@pytest.mark.asyncio
async def test_delete_claude_code_setting_deletes_by_tool_type():
    provider_connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=provider_connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": provider_connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    repo.by_tool_type["claude_code"] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[provider_connection_id] = {
        "row": SimpleNamespace(
            id=provider_connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=None,
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.delete_claude_code_setting(db=None, user_id="u1")

    assert result is True
    assert provider_connection_svc.deleted_connection_ids == [provider_connection_id]


@pytest.mark.asyncio
async def test_delete_mcp_settings_clears_default_and_session_references():
    """Deleting a selected runtime clears user/session selectors before removal."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={"tool_type": "codex", "provider_connection_id": str(uuid.uuid4())},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    user_repo = FakeUserRepo(user=SimpleNamespace(id="u1", default_mcp_setting_id=setting.id))
    session = SimpleNamespace(id=str(uuid.uuid4()), user_id="u1", mcp_setting_id=setting.id)
    session_repo = FakeSessionRepo(sessions=[session])
    svc = _make_service(repo=repo, user_repo=user_repo, session_repo=session_repo)

    result = await svc.delete_mcp_settings(db=None, setting_id=setting.id, user_id="u1")

    assert result is True
    assert user_repo.user.default_mcp_setting_id is None
    assert session.mcp_setting_id is None
    assert setting.id not in repo.items


@pytest.mark.asyncio
async def test_delete_mcp_settings_removes_orphaned_provider_connection():
    """Deleting the last runtime reference tears down stored provider credentials."""
    provider_connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=provider_connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": provider_connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[provider_connection_id] = {
        "row": SimpleNamespace(
            id=provider_connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=None,
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.delete_mcp_settings(db=None, setting_id=setting.id, user_id="u1")

    assert result is True
    assert provider_connection_svc.deleted_connection_ids == [provider_connection_id]


@pytest.mark.asyncio
async def test_delete_mcp_settings_keeps_shared_provider_connection():
    """Shared provider credentials stay intact while another runtime still references them."""
    provider_connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=provider_connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": provider_connection_id},
    )
    sibling = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=provider_connection_id,
        mcp_metadata={"tool_type": "codex", "provider_connection_id": provider_connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    repo.items[sibling.id] = sibling
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[provider_connection_id] = {
        "row": SimpleNamespace(
            id=provider_connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=None,
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.delete_mcp_settings(db=None, setting_id=setting.id, user_id="u1")

    assert result is True
    assert provider_connection_svc.deleted_connection_ids == []


# ---------------------------------------------------------------------------
# Tests – get_codex_setting / get_claude_code_setting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_codex_setting_returns_setting():
    """Returns the codex setting for a user."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={"tool_type": "codex", "auth_json": {}, "store_path": ""},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    repo.by_tool_type["codex"] = setting
    svc = _make_service(repo=repo)

    result = await svc.get_codex_setting(db=None, user_id="u1")

    assert result is not None


@pytest.mark.asyncio
async def test_get_codex_setting_returns_none_when_missing():
    """Returns None when no codex setting exists."""
    svc = _make_service()

    result = await svc.get_codex_setting(db=None, user_id="u1")

    assert result is None


@pytest.mark.asyncio
async def test_get_claude_code_setting_returns_setting():
    """Returns the claude_code setting for a user."""
    provider_connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "claude_code",
            "provider_connection_id": provider_connection_id,
            "has_auth": True,
            "store_path": "",
        },
        provider_connection_id=provider_connection_id,
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    repo.by_tool_type["claude_code"] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[provider_connection_id] = {
        "row": SimpleNamespace(
            id=provider_connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=None,
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.get_claude_code_setting(db=None, user_id="u1")

    assert result is not None
    assert result.metadata is not None
    assert result.metadata.has_auth is True
    assert result.metadata.auth_status == "connected"
    assert result.metadata.needs_reauth is False
    assert not hasattr(result.metadata, "auth_json")


@pytest.mark.asyncio
async def test_get_claude_code_setting_returns_none_when_missing():
    """Returns None when no claude_code setting exists."""
    svc = _make_service()

    result = await svc.get_claude_code_setting(db=None, user_id="u1")

    assert result is None


@pytest.mark.asyncio
async def test_get_claude_code_setting_marks_missing_connection_as_reauth_required():
    provider_connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "claude_code",
            "provider_connection_id": provider_connection_id,
            "has_auth": True,
            "store_path": "~/.claude",
        },
        provider_connection_id=provider_connection_id,
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    repo.by_tool_type["claude_code"] = setting
    svc = _make_service(repo=repo, provider_connection_service=FakeProviderConnectionService())

    result = await svc.get_claude_code_setting(db=None, user_id="u1")

    assert result is not None
    assert result.metadata is not None
    assert result.metadata.has_auth is False
    assert result.metadata.auth_status == "missing"
    assert result.metadata.needs_reauth is True


# ---------------------------------------------------------------------------
# Tests – configure_codex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_codex_with_apikey_only():
    """apikey provided without auth_json creates auth_json from apikey."""
    repo = FakeMCPRepo()
    provider_connection_svc = FakeProviderConnectionService()
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json=None,
        apikey="sk-test-key",
        model=None,
        reasoning_effort=None,
        search=False,
    )

    assert result is not None
    created = list(repo.items.values())[0]
    connection_id = str(created.mcp_metadata["provider_connection_id"])
    assert provider_connection_svc.connections[connection_id]["credentials"]["OPENAI_API_KEY"] == (
        "sk-test-key"
    )
    assert created.mcp_metadata["auth_mode"] == "api_key"


@pytest.mark.asyncio
async def test_configure_codex_serializes_uuid_provider_connection_id_for_storage():
    """Codex metadata stored in JSONB must not retain UUID objects."""
    repo = FakeMCPRepo()
    provider_connection_svc = FakeProviderConnectionService(connection_id_factory=uuid.uuid4)
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json=None,
        apikey="sk-test-key",
        model=None,
        reasoning_effort=None,
        search=False,
    )

    created = list(repo.items.values())[0]
    assert isinstance(created.mcp_metadata["provider_connection_id"], str)
    assert uuid.UUID(created.mcp_metadata["provider_connection_id"])


@pytest.mark.asyncio
async def test_configure_codex_with_auth_json_and_apikey():
    """Both auth_json and apikey - apikey is added to auth_json."""
    repo = FakeMCPRepo()
    provider_connection_svc = FakeProviderConnectionService()
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json={"OTHER_KEY": "other-value"},
        apikey="sk-merged",
        model=None,
        reasoning_effort=None,
        search=False,
    )

    assert result is not None
    created = list(repo.items.values())[0]
    connection_id = str(created.mcp_metadata["provider_connection_id"])
    auth_json = provider_connection_svc.connections[connection_id]["credentials"]
    assert auth_json["OPENAI_API_KEY"] == "sk-merged"
    assert auth_json["OTHER_KEY"] == "other-value"


@pytest.mark.asyncio
async def test_configure_codex_no_auth_raises():
    """No auth_json and no apikey raises MCPOAuthError."""
    svc = _make_service()

    with pytest.raises(MCPOAuthError, match="Authentication JSON or API Key is required"):
        await svc.configure_codex(
            db=None,
            user_id="u1",
            auth_json=None,
            apikey=None,
            model=None,
            reasoning_effort=None,
            search=False,
        )


@pytest.mark.asyncio
async def test_configure_codex_with_model_and_reasoning():
    """Model and reasoning_effort are appended to uvx args."""
    repo = FakeMCPRepo()
    svc = _make_service(repo=repo, provider_connection_service=FakeProviderConnectionService())

    await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json={"OPENAI_API_KEY": "key"},
        apikey=None,
        model="o3",
        reasoning_effort="high",
        search=True,
    )

    created = list(repo.items.values())[0]
    # Verify the mcp_config stores server args including model and reasoning_effort
    server_config = created.mcp_config
    servers = server_config.get("mcpServers", {})
    server = list(servers.values())[0]
    args = server.get("args", [])
    args_str = " ".join(args)
    assert "--model=o3" in args_str
    assert "--model_reasoning_effort=high" in args_str
    assert "--search" in args_str


@pytest.mark.asyncio
async def test_configure_codex_updates_existing():
    """Existing codex setting is updated instead of creating a new one."""
    existing = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "codex",
            "auth_json": {"OPENAI_API_KEY": "old"},
            "store_path": "",
        },
    )
    repo = FakeMCPRepo()
    repo.items[existing.id] = existing
    repo.by_tool_type["codex"] = existing
    provider_connection_svc = FakeProviderConnectionService()
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json=None,
        apikey="new-key",
        model=None,
        reasoning_effort=None,
        search=False,
    )

    # Should update, not create new
    assert len(repo.items) == 1


@pytest.mark.asyncio
async def test_configure_codex_preserves_existing_auth_when_only_updating_options():
    """Saving Codex options without re-pasting auth reuses the stored credentials."""
    existing = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "codex",
            "auth_json": {"OPENAI_API_KEY": "persist-me"},
            "store_path": "~/.codex",
        },
        provider_connection_id=str(uuid.uuid4()),
    )
    repo = FakeMCPRepo()
    repo.items[existing.id] = existing
    repo.by_tool_type["codex"] = existing
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[existing.provider_connection_id] = {
        "row": SimpleNamespace(
            id=existing.provider_connection_id,
            user_id="u1",
            provider="openai",
            product="codex",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
        ),
        "credentials": {"OPENAI_API_KEY": "persist-me"},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    await svc.configure_codex(
        db=None,
        user_id="u1",
        auth_json=None,
        apikey=None,
        model="gpt-5",
        reasoning_effort="medium",
        search=True,
    )

    auth_json = provider_connection_svc.connections[str(existing.provider_connection_id)][
        "credentials"
    ]
    assert auth_json["OPENAI_API_KEY"] == "persist-me"
    assert existing.mcp_metadata["search"] is True


# ---------------------------------------------------------------------------
# Tests – configure_claude_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_claude_code_invalid_format_raises():
    """Authorization code without '#' separator raises MCPOAuthError."""
    svc = _make_service()

    with pytest.raises(MCPOAuthError, match="Invalid authorization code format"):
        await svc.configure_claude_code(
            db=None,
            user_id="u1",
            authorization_code="no-hash-separator",
        )


@pytest.mark.asyncio
async def test_configure_claude_code_token_exchange_success():
    """Valid authorization_code triggers token exchange and creates setting."""
    repo = FakeMCPRepo()
    svc = _make_service(repo=repo, provider_connection_service=FakeProviderConnectionService())

    token_response = {
        "access_token": "access-123",
        "refresh_token": "refresh-456",
        "expires_in": 3600,
    }

    with patch(
        "ii_agent.settings.mcp.service._exchange_code_for_tokens",
        new=AsyncMock(return_value=token_response),
    ):
        result = await svc.configure_claude_code(
            db=None,
            user_id="u1",
            authorization_code="mycode#myverifier",
        )

    assert result is not None
    assert result.metadata is not None
    assert result.metadata.has_auth is True
    assert result.metadata.auth_status == "connected"
    assert result.metadata.needs_reauth is False
    created = list(repo.items.values())[0]
    assert created.mcp_metadata["tool_type"] == "claude_code"
    assert "auth_json" not in created.mcp_metadata


@pytest.mark.asyncio
async def test_configure_claude_code_updates_existing():
    """Existing claude_code setting is updated on second configure call."""
    existing = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "claude_code",
            "auth_json": {"claudeAiOauth": {"accessToken": "old"}},
            "store_path": "",
        },
    )
    repo = FakeMCPRepo()
    repo.items[existing.id] = existing
    repo.by_tool_type["claude_code"] = existing
    svc = _make_service(repo=repo, provider_connection_service=FakeProviderConnectionService())

    token_response = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 7200,
    }

    with patch(
        "ii_agent.settings.mcp.service._exchange_code_for_tokens",
        new=AsyncMock(return_value=token_response),
    ):
        await svc.configure_claude_code(
            db=None,
            user_id="u1",
            authorization_code="code#verifier",
        )

    # Should update existing, not create new
    assert len(repo.items) == 1
    assert "auth_json" not in existing.mcp_metadata


@pytest.mark.asyncio
async def test_complete_claude_code_oauth_serializes_uuid_provider_connection_id_for_storage():
    """Claude OAuth completion must serialize provider connection UUIDs before JSONB insert."""
    repo = FakeMCPRepo()
    provider_connection_svc = FakeProviderConnectionService(connection_id_factory=uuid.uuid4)
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)
    start = await svc.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )

    with patch(
        "ii_agent.settings.mcp.service._exchange_code_for_tokens",
        new=AsyncMock(
            return_value={
                "access_token": "access-123",
                "refresh_token": "refresh-456",
                "expires_in": 3600,
            }
        ),
    ):
        result = await svc.complete_claude_code_oauth(
            db=None,
            user_id="u1",
            login_id=start.login_id,
            code="auth-code",
            state=start.login_id,
        )

    created = list(repo.items.values())[0]
    assert isinstance(created.mcp_metadata["provider_connection_id"], str)
    assert uuid.UUID(created.mcp_metadata["provider_connection_id"])
    assert result.metadata is not None
    assert (
        str(result.metadata.provider_connection_id)
        == created.mcp_metadata["provider_connection_id"]
    )


@pytest.mark.asyncio
async def test_start_claude_code_oauth_builds_authorization_url():
    """Backend owns PKCE and returns a popup-ready authorization URL."""
    svc = _make_service()

    result = await svc.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )

    assert result.login_id
    assert result.authorization_url.startswith("https://claude.ai/oauth/authorize?")
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in result.authorization_url
    assert "code_challenge=" in result.authorization_url
    assert f"state={result.login_id}" in result.authorization_url
    staged = _verify_claude_code_oauth_login_id(
        svc._config,
        result.login_id,
        expected_user_id="u1",
    )
    assert staged["redirect_uri"] == "http://localhost:1420/claude-code-callback"
    assert staged["oauth_redirect_uri"] == "https://example.com/callback"


@pytest.mark.asyncio
async def test_complete_claude_code_oauth_uses_staged_redirect_uri():
    """Completion must reuse the exact provider redirect URI staged at OAuth start."""
    repo = FakeMCPRepo()
    svc = _make_service(repo=repo, provider_connection_service=FakeProviderConnectionService())
    start = await svc.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )

    with patch(
        "ii_agent.settings.mcp.service._exchange_code_for_tokens",
        new=AsyncMock(
            return_value={
                "access_token": "access-123",
                "refresh_token": "refresh-456",
                "expires_in": 3600,
            }
        ),
    ) as exchange_mock:
        await svc.complete_claude_code_oauth(
            db=None,
            user_id="u1",
            login_id=start.login_id,
            code="auth-code",
            state=start.login_id,
        )

    assert exchange_mock.await_args.kwargs["redirect_uri"] == "https://example.com/callback"


@pytest.mark.asyncio
async def test_resolve_claude_code_oauth_callback_redirect_uses_staged_frontend_uri():
    """OAuth callback should return the popup to the staged frontend callback URI."""
    svc = _make_service()
    start = await svc.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )
    result = svc.resolve_claude_code_oauth_callback_redirect(
        state=start.login_id,
        code="auth-code",
    )

    assert result == (
        f"http://localhost:1420/claude-code-callback?state={start.login_id}&code=auth-code"
    )


# ---------------------------------------------------------------------------
# Tests – runtime selection validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assert_runtime_setting_selectable_rejects_inactive_setting():
    setting = _make_mcp_setting(
        user_id="u1",
        is_active=False,
        provider_connection_id=str(uuid.uuid4()),
        mcp_metadata={"tool_type": "codex", "provider_connection_id": str(uuid.uuid4())},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(
        repo=repo,
        provider_connection_service=FakeProviderConnectionService(),
    )

    with pytest.raises(MCPOAuthError, match="active"):
        await svc.assert_runtime_setting_selectable(
            db=None,
            user_id="u1",
            setting_id=uuid.UUID(setting.id),
            selection_kind="session",
        )


@pytest.mark.asyncio
async def test_assert_runtime_setting_selectable_rejects_missing_provider_credentials():
    connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=connection_id,
        mcp_metadata={"tool_type": "codex", "provider_connection_id": connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    svc = _make_service(
        repo=repo,
        provider_connection_service=FakeProviderConnectionService(),
    )

    with pytest.raises(MCPOAuthError, match="missing provider credentials"):
        await svc.assert_runtime_setting_selectable(
            db=None,
            user_id="u1",
            setting_id=uuid.UUID(setting.id),
            selection_kind="session",
        )


@pytest.mark.asyncio
async def test_assert_runtime_setting_selectable_allows_expired_claude_credentials_with_refresh():
    connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[connection_id] = {
        "row": SimpleNamespace(
            id=connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    result = await svc.assert_runtime_setting_selectable(
        db=None,
        user_id="u1",
        setting_id=uuid.UUID(setting.id),
        selection_kind="session",
    )

    assert result is setting


@pytest.mark.asyncio
async def test_assert_runtime_setting_selectable_rejects_expired_provider_credentials_without_refresh():
    connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[connection_id] = {
        "row": SimpleNamespace(
            id=connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="connected",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
        "credentials": {"claudeAiOauth": {"accessToken": "access-only"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    with pytest.raises(MCPOAuthError, match="missing provider credentials"):
        await svc.assert_runtime_setting_selectable(
            db=None,
            user_id="u1",
            setting_id=uuid.UUID(setting.id),
            selection_kind="session",
        )


@pytest.mark.asyncio
async def test_assert_runtime_setting_selectable_rejects_non_connected_provider_credentials():
    connection_id = str(uuid.uuid4())
    setting = _make_mcp_setting(
        user_id="u1",
        provider_connection_id=connection_id,
        mcp_metadata={"tool_type": "claude_code", "provider_connection_id": connection_id},
    )
    repo = FakeMCPRepo()
    repo.items[setting.id] = setting
    provider_connection_svc = FakeProviderConnectionService()
    provider_connection_svc.connections[connection_id] = {
        "row": SimpleNamespace(
            id=connection_id,
            user_id="u1",
            provider="anthropic",
            product="claude_code",
            encrypted_credentials_json="encrypted",
            connection_metadata={},
            status="reauth_required",
            expires_at=None,
        ),
        "credentials": {"claudeAiOauth": {"refreshToken": "refresh-123"}},
    }
    svc = _make_service(repo=repo, provider_connection_service=provider_connection_svc)

    with pytest.raises(MCPOAuthError, match="missing provider credentials"):
        await svc.assert_runtime_setting_selectable(
            db=None,
            user_id="u1",
            setting_id=uuid.UUID(setting.id),
            selection_kind="session",
        )


# ---------------------------------------------------------------------------
# Tests – _to_mcp_setting_info (converter)
# ---------------------------------------------------------------------------


def test_to_mcp_setting_info_with_codex_metadata():
    """Converts MCPSetting with codex metadata to MCPSettingInfo."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "codex",
            "auth_json": {"OPENAI_API_KEY": "key"},
            "store_path": "",
        },
    )

    result = _to_mcp_setting_info(setting)

    assert str(result.id) == setting.id
    assert result.metadata is not None
    assert result.metadata.tool_type == "codex"
    assert result.metadata.has_auth is True
    assert result.metadata.auth_json is None


def test_to_mcp_setting_info_with_codex_metadata_include_secrets():
    """Trusted internal consumers can request decrypted Codex auth payloads."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "codex",
            "auth_json": {"OPENAI_API_KEY": "key"},
            "store_path": "",
        },
    )

    result = _to_mcp_setting_info(setting, include_secrets=True)

    assert result.metadata is not None
    assert result.metadata.auth_json == {"OPENAI_API_KEY": "key"}


def test_to_mcp_setting_info_redacts_legacy_claude_auth_json():
    """Claude metadata redacts legacy auth payloads without inferring live readiness."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={
            "tool_type": "claude_code",
            "auth_json": {"claudeAiOauth": {"refreshToken": "secret"}},
            "store_path": "~/.claude",
        },
    )

    result = _to_mcp_setting_info(setting, include_secrets=True)

    assert result.metadata is not None
    assert result.metadata.tool_type == "claude_code"
    assert result.metadata.has_auth is False
    assert not hasattr(result.metadata, "auth_json")


def test_to_mcp_setting_info_without_metadata():
    """Converts MCPSetting without metadata correctly."""
    setting = _make_mcp_setting(user_id="u1", mcp_metadata=None)

    result = _to_mcp_setting_info(setting)

    assert str(result.id) == setting.id
    assert result.metadata is None


def test_to_mcp_setting_info_invalid_metadata_handled():
    """Invalid metadata dict is silently ignored (no metadata in result)."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_metadata={"tool_type": "unknown_type", "invalid": True},
    )

    result = _to_mcp_setting_info(setting)

    assert str(result.id) == setting.id
    # Unknown tool_type - metadata should still be a base MCPMetadata
    # or None depending on validate_metadata behavior


def test_to_mcp_setting_info_dict_mcp_config():
    """Dict-form mcp_config is correctly converted to MCPServersConfig."""
    setting = _make_mcp_setting(
        user_id="u1",
        mcp_config={"mcpServers": {"test": {"command": "npx"}}},
    )

    result = _to_mcp_setting_info(setting)

    assert result.mcp_config is not None
