from types import SimpleNamespace

import pytest

from ii_agent.settings.mcp.exceptions import MCPOAuthError
from ii_agent.settings.mcp.service import (
    _exchange_code_for_tokens,
    _sanitize_claude_code_redirect_uri,
    _to_mcp_setting_info,
)


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_http_error(monkeypatch):
    class FakeResponse:
        is_success = False
        text = "failure"

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "ii_agent.settings.mcp.service.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    with pytest.raises(MCPOAuthError):
        await _exchange_code_for_tokens(
            "code",
            "verifier",
            SimpleNamespace(
                anthropic_oauth_token_url="https://token",
                anthropic_oauth_client_id="client",
                anthropic_oauth_redirect_uri="https://callback",
            ),
            redirect_uri="https://callback",
        )


def test_sanitize_claude_code_redirect_uri_accepts_local_frontend():
    result = _sanitize_claude_code_redirect_uri(
        SimpleNamespace(
            ii_frontend_url="http://localhost:1420",
            environment="local",
        ),
        "http://localhost:1420/claude-code-callback",
    )

    assert result == "http://localhost:1420/claude-code-callback"


def test_sanitize_claude_code_redirect_uri_rejects_wrong_path():
    with pytest.raises(MCPOAuthError, match="/claude-code-callback"):
        _sanitize_claude_code_redirect_uri(
            SimpleNamespace(
                ii_frontend_url="http://localhost:1420",
                environment="local",
            ),
            "http://localhost:1420/not-allowed",
        )


def test_to_mcp_setting_info_tolerates_malformed_metadata():
    setting = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        mcp_config={"mcpServers": {}},
        mcp_metadata={"bad": "shape"},
        is_active=True,
        created_at=None,
        updated_at=None,
    )

    info = _to_mcp_setting_info(setting)

    assert str(info.id) == "11111111-1111-1111-1111-111111111111"
    assert info.metadata is None
