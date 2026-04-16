from __future__ import annotations

import base64
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _get_auth_router_module():
    return importlib.import_module("ii_agent.auth.router")


def _make_fake_jwt(payload: dict[str, object]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{body}.sig"


@pytest.mark.asyncio
async def test_auth_providers_treats_dev_bypass_as_available():
    mod = _get_auth_router_module()
    settings = SimpleNamespace(
        oauth=SimpleNamespace(
            has_ii_oauth=lambda: False,
            has_google_oauth=lambda: False,
        ),
        is_dev_auth_bypass_enabled=True,
    )

    response = await mod.auth_providers(settings)

    assert response.ii_oauth_available is True
    assert response.dev_auth_bypass_enabled is True
    assert response.google_oauth_available is False


@pytest.mark.asyncio
async def test_ii_login_uses_dev_bypass_when_ii_oauth_missing():
    mod = _get_auth_router_module()
    request = SimpleNamespace(session={}, headers={})
    user = SimpleNamespace(
        id="user-123",
        email="dev@ii-agent.local",
        role="user",
    )
    settings = SimpleNamespace(
        oauth=SimpleNamespace(ii_client_id=""),
        is_dev_auth_bypass_enabled=True,
        dev_auth_bypass_email="dev@ii-agent.local",
        dev_auth_bypass_first_name="Local",
        dev_auth_bypass_last_name="Developer",
    )
    user_service = MagicMock()
    user_service.find_or_create_oauth_user = AsyncMock(return_value=user)
    mcp_service = MagicMock()
    mcp_service.configure_codex = AsyncMock()
    db = object()

    with patch.object(mod, "jwt_handler") as mock_handler:
        mock_handler.create_access_token.return_value = "access-token"
        mock_handler.create_refresh_token.return_value = "refresh-token"
        mock_handler.access_token_expire_minutes = 30

        response = await mod.ii_login(
            request=request,
            db=db,
            settings=settings,
            user_service=user_service,
            mcp_service=mcp_service,
            return_to="http://localhost:1420/login",
            openai_pending=None,
        )

    assert response.status_code == 200
    user_service.find_or_create_oauth_user.assert_awaited_once()
    mcp_service.configure_codex.assert_not_awaited()
    assert "ii-auth" in response.body.decode()


@pytest.mark.asyncio
async def test_ii_login_dev_bypass_uses_staged_openai_identity_and_attaches_codex():
    mod = _get_auth_router_module()
    request = SimpleNamespace(session={}, headers={})
    id_token = _make_fake_jwt(
        {
            "email": "openai-user@example.com",
            "email_verified": True,
            "given_name": "Open",
            "family_name": "AI",
            "picture": "https://example.com/avatar.png",
            "sub": "acct_123",
        }
    )
    pending_id = await mod._stage_pending_openai_connection(
        auth_json={
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": id_token,
                "access_token": "oa-access",
                "refresh_token": "oa-refresh",
            },
        },
        model="gpt-5",
        reasoning_effort="medium",
        search=True,
    )
    user = SimpleNamespace(
        id="user-openai",
        email="openai-user@example.com",
        role="user",
    )
    settings = SimpleNamespace(
        oauth=SimpleNamespace(ii_client_id=""),
        is_dev_auth_bypass_enabled=True,
        dev_auth_bypass_email="dev@ii-agent.local",
        dev_auth_bypass_first_name="Local",
        dev_auth_bypass_last_name="Developer",
    )
    user_service = MagicMock()
    user_service.find_or_create_oauth_user = AsyncMock(return_value=user)
    mcp_service = MagicMock()
    mcp_service.configure_codex = AsyncMock()
    db = object()

    try:
        with patch.object(mod, "jwt_handler") as mock_handler:
            mock_handler.create_access_token.return_value = "access-token"
            mock_handler.create_refresh_token.return_value = "refresh-token"
            mock_handler.access_token_expire_minutes = 30

            response = await mod.ii_login(
                request=request,
                db=db,
                settings=settings,
                user_service=user_service,
                mcp_service=mcp_service,
                return_to="http://localhost:1420/login",
                openai_pending=pending_id,
            )
    finally:
        await mod._clear_pending_openai_connection(pending_id)

    assert response.status_code == 200
    user_service.find_or_create_oauth_user.assert_awaited_once_with(
        db,
        email="openai-user@example.com",
        first_name="Open",
        last_name="AI",
        avatar="https://example.com/avatar.png",
        email_verified=True,
        login_provider="dev_bypass",
    )
    mcp_service.configure_codex.assert_awaited_once()
