import pytest

from ii_agent.settings.mcp.router import router
from tests.api.contracts import assert_auth_contract, assert_routes_present

pytestmark = pytest.mark.unit


EXPECTED_ROUTES = {
    ("GET", "/mcp/codex"),
    ("POST", "/mcp/codex"),
    ("POST", "/mcp/codex/openai/device/start"),
    ("POST", "/mcp/codex/openai/device/poll"),
    ("GET", "/mcp/claude-code"),
    ("POST", "/mcp/claude-code"),
    ("POST", "/mcp/claude-code/oauth/start"),
    ("POST", "/mcp/claude-code/oauth/complete"),
    ("POST", "/mcp"),
    ("GET", "/mcp"),
    ("GET", "/mcp/{setting_id}"),
    ("PUT", "/mcp/{setting_id}"),
    ("DELETE", "/mcp/{setting_id}"),
}


def test_mcp_router_routes_registered():
    assert_routes_present(router, EXPECTED_ROUTES)


def test_mcp_router_auth_contract():
    assert_auth_contract(router, protected=EXPECTED_ROUTES)
