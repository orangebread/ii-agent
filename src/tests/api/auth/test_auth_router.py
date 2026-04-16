import pytest

from ii_agent.auth.router import router
from tests.api.contracts import assert_auth_contract, assert_routes_present

pytestmark = pytest.mark.unit


EXPECTED_ROUTES = {
    ("GET", "/auth/providers"),
    ("GET", "/auth/oauth/ii/login"),
    ("GET", "/auth/oauth/ii/callback"),
    ("GET", "/auth/oauth/google/login"),
    ("GET", "/auth/oauth/google/callback"),
    ("POST", "/auth/oauth/openai/device/start"),
    ("POST", "/auth/oauth/openai/device/poll"),
    ("GET", "/auth/me"),
}


def test_auth_router_routes_registered():
    assert_routes_present(router, EXPECTED_ROUTES)


def test_auth_router_auth_contract():
    assert_auth_contract(
        router,
        protected={("GET", "/auth/me")},
        public=EXPECTED_ROUTES - {("GET", "/auth/me")},
    )
