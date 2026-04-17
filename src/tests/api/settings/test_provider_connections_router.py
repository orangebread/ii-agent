import pytest

from ii_agent.settings.provider_connections.router import router
from tests.api.contracts import assert_auth_contract, assert_routes_present

pytestmark = pytest.mark.unit


EXPECTED_ROUTES = {
    ("GET", "/provider-connections"),
    ("GET", "/provider-connections/{connection_id}"),
}


def test_provider_connections_router_routes_registered():
    assert_routes_present(router, EXPECTED_ROUTES)


def test_provider_connections_router_auth_contract():
    assert_auth_contract(router, protected=EXPECTED_ROUTES)
