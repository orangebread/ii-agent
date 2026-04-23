from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ii_agent.core.exceptions import ServiceUnavailableError
from ii_agent.integrations.connectors.composio.auth_config_service import AuthConfigService
from ii_agent.integrations.connectors.composio.connected_account_service import (
    ConnectedAccountService,
)
from ii_agent.integrations.connectors.composio.mcp_server_service import MCPServerService
from ii_agent.integrations.connectors.composio.toolkit_service import ToolkitService


def test_composio_services_do_not_resolve_client_during_init():
    with (
        patch(
            "ii_agent.integrations.connectors.composio.toolkit_service.ComposioClient.get_client",
            side_effect=AssertionError("toolkit client should be lazy"),
        ),
        patch(
            "ii_agent.integrations.connectors.composio.auth_config_service.ComposioClient.get_client",
            side_effect=AssertionError("auth config client should be lazy"),
        ),
        patch(
            "ii_agent.integrations.connectors.composio.connected_account_service.ComposioClient.get_client",
            side_effect=AssertionError("connected account client should be lazy"),
        ),
        patch(
            "ii_agent.integrations.connectors.composio.mcp_server_service.ComposioClient.get_client",
            side_effect=AssertionError("mcp server client should be lazy"),
        ),
    ):
        ToolkitService()
        AuthConfigService()
        ConnectedAccountService()
        MCPServerService()


@pytest.mark.asyncio
async def test_toolkit_service_resolves_client_on_first_use():
    fake_client = MagicMock()
    fake_client.toolkits.get.return_value = []

    with patch(
        "ii_agent.integrations.connectors.composio.toolkit_service.ComposioClient.get_client",
        return_value=fake_client,
    ) as get_client:
        service = ToolkitService()
        result = await service.list_toolkits()

    assert result["success"] is True
    get_client.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_toolkit_service_reports_invalid_server_api_key():
    class FakeAuthError(Exception):
        pass

    fake_client = MagicMock()
    fake_client.toolkits.get.side_effect = FakeAuthError("bad composio key")

    with (
        patch(
            "ii_agent.integrations.connectors.composio.toolkit_service.ComposioAuthenticationError",
            FakeAuthError,
        ),
        patch(
            "ii_agent.integrations.connectors.composio.toolkit_service.ComposioClient.get_client",
            return_value=fake_client,
        ),
    ):
        service = ToolkitService()
        with pytest.raises(ServiceUnavailableError, match="server Composio API key is invalid"):
            await service.list_toolkits()


@pytest.mark.asyncio
async def test_auth_config_service_resolves_client_on_first_use():
    fake_client = MagicMock()
    fake_client.auth_configs.get.return_value = MagicMock(
        id="auth-1",
        auth_scheme="OAUTH2",
        is_composio_managed=True,
        toolkit_slug="gmail",
    )

    with patch(
        "ii_agent.integrations.connectors.composio.auth_config_service.ComposioClient.get_client",
        return_value=fake_client,
    ) as get_client:
        service = AuthConfigService()
        result = await service.get_auth_config("auth-1")

    assert result is not None
    assert result.id == "auth-1"
    get_client.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_connected_account_service_resolves_client_on_first_use():
    fake_client = MagicMock()
    fake_client.connected_accounts.get.return_value = SimpleNamespace(
        id="conn-1",
        status="ACTIVE",
        redirect_url="https://example.com/oauth",
        redirect_uri="https://example.com/oauth",
        auth_config_id="auth-1",
        user_id="user-1",
        state=SimpleNamespace(auth_scheme="OAUTH2", val={"status": "ACTIVE"}),
    )

    with patch(
        "ii_agent.integrations.connectors.composio.connected_account_service.ComposioClient.get_client",
        return_value=fake_client,
    ) as get_client:
        service = ConnectedAccountService()
        result = await service.get_connected_account("conn-1")

    assert result is not None
    assert result.id == "conn-1"
    get_client.assert_called_once_with(None)


def test_mcp_server_service_resolves_client_on_first_use():
    fake_client = MagicMock()
    fake_client.mcp.get.return_value = MagicMock(
        id="mcp-1",
        name="gmail-abcd1234",
        auth_config_ids=[],
        allowed_tools=[],
        toolkits=[],
        commands=None,
    )

    with patch(
        "ii_agent.integrations.connectors.composio.mcp_server_service.ComposioClient.get_client",
        return_value=fake_client,
    ) as get_client:
        service = MCPServerService()
        result = service._call_mcp_get("mcp-1")

    assert result.id == "mcp-1"
    get_client.assert_called_once_with(None)
