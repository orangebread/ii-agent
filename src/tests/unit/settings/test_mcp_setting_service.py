from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ii_agent.settings.mcp.exceptions import MCPOAuthError
from ii_agent.settings.mcp.schemas import MCPServersConfig
from ii_agent.settings.mcp.service import MCPSettingService, _extract_codex_auth_json


class FakeMCPRepo:
    def __init__(self):
        self.active = []
        self.created = []
        self.updated = []
        self.by_tool = {}

    async def list_active_by_user(self, db, user_id):
        return self.active

    async def update(self, db, setting):
        self.updated.append(setting)
        return setting

    async def create(self, db, setting):
        self.created.append(setting)
        return setting

    async def get_by_user_and_tool_type(self, db, user_id, tool_type):
        return self.by_tool.get(tool_type)

    async def get_by_id_and_user(self, db, setting_id, user_id):
        return None

    async def list_by_user(self, db, user_id, only_active=False, no_metadata=False):
        return []

    async def delete(self, db, setting):
        return None


@pytest.mark.asyncio
async def test_create_mcp_settings_deactivates_previous_active(settings_factory):
    active_setting = SimpleNamespace(is_active=True, updated_at=None)
    repo = FakeMCPRepo()
    repo.active = [active_setting]

    service = MCPSettingService(repo=repo, config=settings_factory())

    result = await service.create_mcp_settings(
        db=None,
        user_id="u1",
        mcp_setting_in=SimpleNamespace(
            mcp_config=MCPServersConfig(mcpServers={}),
            metadata=None,
        ),
    )

    assert active_setting.is_active is False
    assert len(repo.created) == 1
    assert result.is_active is True


@pytest.mark.asyncio
async def test_configure_codex_requires_auth_or_api_key(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())

    with pytest.raises(MCPOAuthError):
        await service.configure_codex(
            db=None,
            user_id="u1",
            auth_json=None,
            apikey=None,
            model=None,
            reasoning_effort=None,
            search=False,
        )


@pytest.mark.asyncio
async def test_configure_claude_code_validates_authorization_format(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())

    with pytest.raises(MCPOAuthError, match="Invalid authorization code format"):
        await service.configure_claude_code(
            db=None,
            user_id="u1",
            authorization_code="invalid-format",
        )


@pytest.mark.asyncio
async def test_start_claude_code_oauth_returns_login_data(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())

    result = await service.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )

    assert result.login_id
    assert result.authorization_url.startswith("https://claude.ai/oauth/authorize?")
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1420%2Fclaude-code-callback" in (
        result.authorization_url
    )


@pytest.mark.asyncio
async def test_complete_claude_code_oauth_validates_state(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())
    start = await service.start_claude_code_oauth(
        user_id="u1",
        redirect_uri="http://localhost:1420/claude-code-callback",
    )

    with pytest.raises(MCPOAuthError, match="state mismatch"):
        await service.complete_claude_code_oauth(
            db=None,
            user_id="u1",
            login_id=start.login_id,
            code="auth-code",
            state="wrong-state",
        )


@pytest.mark.asyncio
async def test_start_codex_openai_device_oauth_returns_login_data(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())

    with patch(
        "ii_agent.settings.mcp.service._request_openai_device_code",
        new=AsyncMock(
            return_value={
                "device_auth_id": "device-auth-123",
                "user_code": "ABCD-1234",
                "interval_seconds": 5,
                "verification_url": "https://auth.openai.com/codex/device",
            }
        ),
    ):
        result = await service.start_codex_openai_device_oauth(
            user_id="u1",
            model="gpt-5",
            reasoning_effort="medium",
            search=True,
        )

    assert result.user_code == "ABCD-1234"
    assert result.verification_url == "https://auth.openai.com/codex/device"
    assert result.login_id


@pytest.mark.asyncio
async def test_poll_codex_openai_device_oauth_returns_pending(settings_factory):
    service = MCPSettingService(repo=FakeMCPRepo(), config=settings_factory())

    with patch(
        "ii_agent.settings.mcp.service._request_openai_device_code",
        new=AsyncMock(
            return_value={
                "device_auth_id": "device-auth-123",
                "user_code": "ABCD-1234",
                "interval_seconds": 5,
                "verification_url": "https://auth.openai.com/codex/device",
            }
        ),
    ):
        start = await service.start_codex_openai_device_oauth(
            user_id="u1",
            model="gpt-5",
            reasoning_effort="medium",
            search=False,
        )

    with patch(
        "ii_agent.settings.mcp.service._poll_openai_device_code",
        new=AsyncMock(return_value=None),
    ):
        result = await service.poll_codex_openai_device_oauth(
            db=None,
            user_id="u1",
            login_id=start.login_id,
        )

    assert result.status == "pending"


@pytest.mark.asyncio
async def test_poll_codex_openai_device_oauth_persists_codex_setting(settings_factory):
    repo = FakeMCPRepo()
    service = MCPSettingService(repo=repo, config=settings_factory())

    with patch(
        "ii_agent.settings.mcp.service._request_openai_device_code",
        new=AsyncMock(
            return_value={
                "device_auth_id": "device-auth-123",
                "user_code": "ABCD-1234",
                "interval_seconds": 5,
                "verification_url": "https://auth.openai.com/codex/device",
            }
        ),
    ):
        start = await service.start_codex_openai_device_oauth(
            user_id="u1",
            model="gpt-5",
            reasoning_effort="medium",
            search=True,
        )

    with (
        patch(
            "ii_agent.settings.mcp.service._poll_openai_device_code",
            new=AsyncMock(
                return_value={
                    "authorization_code": "auth-code",
                    "code_verifier": "verifier-123",
                }
            ),
        ),
        patch(
            "ii_agent.settings.mcp.service._exchange_openai_device_code",
            new=AsyncMock(
                return_value={
                    "id_token": "eyJhbGciOiJub25lIn0.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9wbGFuX3R5cGUiOiJwbHVzIiwiY2hhdGdwdF9hY2NvdW50X2lkIjoib3JnLTEyMyJ9fQ.c2ln",
                    "access_token": "access-123",
                    "refresh_token": "refresh-123",
                }
            ),
        ),
    ):
        result = await service.poll_codex_openai_device_oauth(
            db=None,
            user_id="u1",
            login_id=start.login_id,
        )

    assert result.status == "completed"
    assert len(repo.created) == 1
    stored = repo.created[0]
    auth_json = _extract_codex_auth_json(stored.mcp_metadata)
    assert auth_json["tokens"]["refresh_token"] == "refresh-123"
    assert stored.mcp_metadata["auth_mode"] == "openai_oauth"
