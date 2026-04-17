from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ii_agent.settings.mcp.service import MCPSettingService


def _setting(tool_type: str, *, is_active: bool = True, user_id="user-1"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        provider_connection_id=uuid.uuid4(),
        mcp_config={"mcpServers": {}},
        mcp_metadata={"tool_type": tool_type},
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class FakeMCPRepo:
    def __init__(self, settings):
        self.settings = {str(setting.id): setting for setting in settings}

    async def get_by_id_and_user(self, db, setting_id, user_id):
        setting = self.settings.get(str(setting_id))
        if setting and str(setting.user_id) == str(user_id):
            return setting
        return None

    async def list_runtime_settings_by_user(self, db, user_id, *, only_active=False):
        rows = list(self.settings.values())
        if only_active:
            rows = [row for row in rows if row.is_active]
        return rows


class FakeUserRepo:
    def __init__(self, default_mcp_setting_id=None):
        self.user = SimpleNamespace(id="user-1", default_mcp_setting_id=default_mcp_setting_id)

    async def get_by_id(self, db, user_id):
        return self.user

    async def set_default_mcp_setting_id(self, db, user, setting_id):
        user.default_mcp_setting_id = setting_id


class FakeSessionRepo:
    def __init__(self, mcp_setting_id=None):
        self.session = SimpleNamespace(id=uuid.uuid4(), mcp_setting_id=mcp_setting_id)

    async def get_by_id(self, db, session_id):
        return self.session


class FakeProviderConnectionService:
    def __init__(self, available_ids=None):
        self.available_ids = {str(connection_id) for connection_id in (available_ids or set())}

    async def get_connection_model(self, db, *, connection_id, user_id):
        if str(connection_id) not in self.available_ids:
            return None
        return SimpleNamespace(id=connection_id, user_id=user_id)

    def get_credentials_dict(self, connection):
        return {"token": "present"}


@pytest.mark.asyncio
async def test_resolve_effective_runtime_prefers_session_override():
    codex = _setting("codex")
    claude = _setting("claude_code")
    repo = FakeMCPRepo([codex, claude])
    service = MCPSettingService(
        repo=repo,
        config=SimpleNamespace(),
        user_repo=FakeUserRepo(default_mcp_setting_id=codex.id),
        session_repo=FakeSessionRepo(mcp_setting_id=claude.id),
        provider_connection_service=FakeProviderConnectionService(
            {codex.provider_connection_id, claude.provider_connection_id}
        ),
    )

    selected = await service.resolve_effective_runtime_setting(
        db=None,
        user_id="user-1",
        session_id=uuid.uuid4(),
    )

    assert selected.id == claude.id


@pytest.mark.asyncio
async def test_resolve_effective_runtime_falls_back_to_default():
    codex = _setting("codex")
    claude = _setting("claude_code")
    repo = FakeMCPRepo([codex, claude])
    service = MCPSettingService(
        repo=repo,
        config=SimpleNamespace(),
        user_repo=FakeUserRepo(default_mcp_setting_id=codex.id),
        session_repo=FakeSessionRepo(mcp_setting_id=None),
        provider_connection_service=FakeProviderConnectionService(
            {codex.provider_connection_id, claude.provider_connection_id}
        ),
    )

    selected = await service.resolve_effective_runtime_setting(
        db=None,
        user_id="user-1",
        session_id=uuid.uuid4(),
    )

    assert selected.id == codex.id


@pytest.mark.asyncio
async def test_resolve_effective_runtime_skips_unusable_fallback_and_uses_valid_runtime():
    shared_user_id = uuid.uuid4()
    codex = _setting("codex", user_id=shared_user_id)
    claude = _setting("claude_code", user_id=shared_user_id)
    codex.provider_connection_id = None
    repo = FakeMCPRepo([codex, claude])
    service = MCPSettingService(
        repo=repo,
        config=SimpleNamespace(),
        user_repo=FakeUserRepo(default_mcp_setting_id=None),
        session_repo=FakeSessionRepo(mcp_setting_id=None),
        provider_connection_service=FakeProviderConnectionService({claude.provider_connection_id}),
    )

    selected = await service.resolve_effective_runtime_setting(
        db=None,
        user_id=shared_user_id,
        session_id=uuid.uuid4(),
    )

    assert selected.id == claude.id
