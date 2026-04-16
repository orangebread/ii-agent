"""Unit tests for auth router and OIDC verification (r4)."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _get_auth_router_module():
    """Get the ii_agent.auth.router module object (not the router APIRouter instance)."""
    return importlib.import_module("ii_agent.auth.router")


# ---------------------------------------------------------------------------
# Helper functions from auth/router.py
# ---------------------------------------------------------------------------


class TestMakeStateR4:
    def test_make_state_returns_string(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            state = mod._make_state()
        assert isinstance(state, str)
        assert len(state) > 0

    def test_make_state_is_different_each_call(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            s1 = mod._make_state()
            s2 = mod._make_state()
        assert s1 != s2


class TestVerifyStateR4:
    def test_verify_state_valid(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            state = mod._make_state()
            result = mod._verify_state(state)
        assert result is True

    def test_verify_state_invalid(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            result = mod._verify_state("tampered-state-value")
        assert result is False

    def test_verify_state_empty(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            result = mod._verify_state("")
        assert result is False


class TestMakePkcePairR4:
    def test_returns_two_strings(self):
        mod = _get_auth_router_module()
        verifier, challenge = mod._make_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_is_url_safe(self):
        mod = _get_auth_router_module()
        verifier, _ = mod._make_pkce_pair()
        assert "+" not in verifier
        assert "/" not in verifier
        assert "=" not in verifier

    def test_challenge_is_url_safe(self):
        mod = _get_auth_router_module()
        _, challenge = mod._make_pkce_pair()
        assert "+" not in challenge
        assert "/" not in challenge
        assert "=" not in challenge

    def test_challenge_is_sha256_of_verifier(self):
        mod = _get_auth_router_module()
        verifier, challenge = mod._make_pkce_pair()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == expected

    def test_different_calls_return_different_pairs(self):
        mod = _get_auth_router_module()
        v1, c1 = mod._make_pkce_pair()
        v2, c2 = mod._make_pkce_pair()
        assert v1 != v2
        assert c1 != c2


class TestSanitizeReturnToR4:
    def test_returns_none_none_for_empty(self):
        mod = _get_auth_router_module()
        origin, url = mod._sanitize_return_to(None)
        assert origin is None
        assert url is None

    def test_returns_none_none_for_blank(self):
        mod = _get_auth_router_module()
        origin, url = mod._sanitize_return_to("")
        assert origin is None
        assert url is None

    def test_valid_https_url(self):
        mod = _get_auth_router_module()
        origin, url = mod._sanitize_return_to("https://app.example.com/dashboard")
        assert origin == "https://app.example.com"
        assert url == "https://app.example.com/dashboard"

    def test_raises_for_relative_url(self):
        mod = _get_auth_router_module()
        from ii_agent.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            mod._sanitize_return_to("/relative/path")

    def test_raises_for_javascript_scheme(self):
        mod = _get_auth_router_module()
        from ii_agent.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            mod._sanitize_return_to("javascript:alert(1)")

    def test_valid_http_url(self):
        mod = _get_auth_router_module()
        origin, url = mod._sanitize_return_to("http://localhost:3000/callback")
        assert origin == "http://localhost:3000"
        assert url == "http://localhost:3000/callback"


class TestMakeTokenPayloadR4:
    def test_returns_token_dict_with_required_keys(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "jwt_handler") as mock_handler:
            mock_handler.create_access_token.return_value = "access-token-value"
            mock_handler.create_refresh_token.return_value = "refresh-token-value"
            mock_handler.access_token_expire_minutes = 15
            payload = mod._make_token_payload("user-id", "user@test.com", "user")
        assert "access_token" in payload
        assert "refresh_token" in payload
        assert "token_type" in payload
        assert "expires_in" in payload

    def test_token_type_is_bearer(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "jwt_handler") as mock_handler:
            mock_handler.create_access_token.return_value = "at"
            mock_handler.create_refresh_token.return_value = "rt"
            mock_handler.access_token_expire_minutes = 30
            payload = mod._make_token_payload("uid", "e@e.com", "user")
        assert payload["token_type"] == "bearer"

    def test_expires_in_calculated_correctly(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "jwt_handler") as mock_handler:
            mock_handler.create_access_token.return_value = "at"
            mock_handler.create_refresh_token.return_value = "rt"
            mock_handler.access_token_expire_minutes = 60
            payload = mod._make_token_payload("uid", "e@e.com", "user")
        assert payload["expires_in"] == 60 * 60


class TestOpenAIIdentityExtractionR4:
    def test_extract_openai_identity_uses_email_when_present(self):
        mod = _get_auth_router_module()
        payload = {
            "email": "user@example.com",
            "email_verified": True,
            "given_name": "Ada",
            "family_name": "Lovelace",
            "picture": "https://example.com/avatar.png",
            "sub": "sub_123",
        }
        token = ".".join(
            [
                "header",
                base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode(),
                "sig",
            ]
        )

        identity = mod._extract_openai_identity(token)

        assert identity["email"] == "user@example.com"
        assert identity["first_name"] == "Ada"
        assert identity["last_name"] == "Lovelace"
        assert identity["email_verified"] is True

    def test_extract_openai_identity_builds_fallback_email(self):
        mod = _get_auth_router_module()
        payload = {
            "name": "Grace Hopper",
            "sub": "acct_123",
        }
        token = ".".join(
            [
                "header",
                base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode(),
                "sig",
            ]
        )

        identity = mod._extract_openai_identity(token)

        assert identity["email"] == "openai-acct_123@users.openai.local"
        assert identity["first_name"] == "Grace"
        assert identity["last_name"] == "Hopper"


class TestIINameExtractionR4:
    def test_extract_ii_name_parts_supports_structured_name(self):
        mod = _get_auth_router_module()

        first_name, last_name = mod._extract_ii_name_parts(
            {"name": {"first": "Ada", "last": "Lovelace"}}
        )

        assert first_name == "Ada"
        assert last_name == "Lovelace"

    def test_extract_ii_name_parts_supports_flat_name(self):
        mod = _get_auth_router_module()

        first_name, last_name = mod._extract_ii_name_parts({"name": "Grace Hopper"})

        assert first_name == "Grace"
        assert last_name == "Hopper"


class TestOpenAIPendingBridgeR4:
    @pytest.mark.asyncio
    async def test_stage_get_and_clear_pending_openai_connection(self):
        mod = _get_auth_router_module()

        pending_id = await mod._stage_pending_openai_connection(
            auth_json={"OPENAI_API_KEY": "secret"},
            model="gpt-5",
            reasoning_effort="medium",
            search=False,
        )

        stored_id, payload = await mod._get_pending_openai_connection(pending_id)
        assert stored_id == pending_id
        assert payload is not None
        assert payload["auth_json"] == {"OPENAI_API_KEY": "secret"}
        assert payload["model"] == "gpt-5"
        assert payload["reasoning_effort"] == "medium"
        assert payload["search"] is False

        await mod._clear_pending_openai_connection(pending_id)
        _, cleared_payload = await mod._get_pending_openai_connection(pending_id)
        assert cleared_payload is None

    @pytest.mark.asyncio
    async def test_ii_login_persists_openai_pending_id_in_session(self):
        mod = _get_auth_router_module()
        request = SimpleNamespace(session={}, headers={})
        settings = SimpleNamespace(
            oauth=SimpleNamespace(
                ii_client_id="client-id",
                ii_redirect_uri="http://localhost:8000/auth/oauth/ii/callback",
                ii_scope="openid profile email",
            ),
            ii_auth_url="https://auth.example.com/oauth2/auth",
        )

        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.session_secret_key = "test-secret"
            response = await mod.ii_login(
                request=request,
                db=object(),
                settings=settings,
                user_service=MagicMock(),
                mcp_service=MagicMock(),
                return_to="http://localhost:1420/login",
                openai_pending="pending-123",
            )

        assert request.session[mod.OPENAI_PENDING_CONNECT_STATE_SESSION_KEY] == "pending-123"
        assert response.status_code == 302
        assert "client_id=client-id" in response.headers["location"]


class TestExchangeCodeForTokenR4:
    @pytest.mark.asyncio
    async def test_raises_bad_gateway_on_non_200(self):
        mod = _get_auth_router_module()
        from ii_agent.core.exceptions import BadGatewayError

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with (
            patch.object(mod, "get_settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_class,
        ):
            mock_settings.return_value.oauth.ii_redirect_uri = "https://app.com/callback"
            mock_settings.return_value.oauth.ii_client_id = "client-id"
            mock_settings.return_value.ii_token_url = "https://auth.example.com/token"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(BadGatewayError, match="Token exchange failed"):
                await mod._exchange_code_for_token("code-123", None)

    @pytest.mark.asyncio
    async def test_returns_json_on_success(self):
        mod = _get_auth_router_module()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "at", "id_token": "it"}

        with (
            patch.object(mod, "get_settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_class,
        ):
            mock_settings.return_value.oauth.ii_redirect_uri = "https://app.com/callback"
            mock_settings.return_value.oauth.ii_client_id = "client-id"
            mock_settings.return_value.ii_token_url = "https://auth.example.com/token"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await mod._exchange_code_for_token("code-123", "verifier-abc")
        assert result["access_token"] == "at"


class TestFetchUserinfoIfEnabledR4:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.ii_use_userinfo = False
            result = await mod._fetch_userinfo_if_enabled("access-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_token(self):
        mod = _get_auth_router_module()
        with patch.object(mod, "get_settings") as mock_settings:
            mock_settings.return_value.oauth.ii_use_userinfo = True
            result = await mod._fetch_userinfo_if_enabled(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_bad_gateway_when_userinfo_fails(self):
        mod = _get_auth_router_module()
        from ii_agent.core.exceptions import BadGatewayError

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with (
            patch.object(mod, "get_settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_class,
        ):
            mock_settings.return_value.oauth.ii_use_userinfo = True
            mock_settings.return_value.oauth.ii_userinfo_url = "https://auth.example.com/userinfo"

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(BadGatewayError, match="userinfo failed"):
                await mod._fetch_userinfo_if_enabled("bad-token")


class TestReaderUserMeR4:
    def test_serialize_user_public_uses_effective_billing_profile(self):
        mod = _get_auth_router_module()
        current_user = SimpleNamespace(
            id="user-1",
            email="user@example.com",
            role="user",
            first_name="Ada",
            last_name="Lovelace",
            avatar="https://example.com/avatar.png",
            language="en",
        )
        billing_profile = mod.EffectiveBillingProfile(
            external_customer_id="cus_new",
            subscription_plan="pro",
            subscription_status="active",
            subscription_billing_cycle="monthly",
            subscription_current_period_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        result = mod._serialize_user_public(current_user, billing_profile)

        assert result.subscription_plan == "pro"
        assert result.subscription_status == "active"
        assert result.subscription_billing_cycle == "monthly"

    @pytest.mark.asyncio
    async def test_reader_user_me_prefers_billing_customer_service(self):
        mod = _get_auth_router_module()
        current_user = SimpleNamespace(
            id="user-1",
            email="user@example.com",
            role="user",
            first_name="Ada",
            last_name="Lovelace",
            avatar=None,
            language="en",
            subscription_plan="legacy-free",
            subscription_status="legacy-status",
            subscription_billing_cycle="monthly",
            subscription_current_period_end=None,
            stripe_customer_id="cus_legacy",
        )
        billing_profile = mod.EffectiveBillingProfile(
            external_customer_id="cus_new",
            subscription_plan="pro",
            subscription_status="active",
            subscription_billing_cycle="annually",
            subscription_current_period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        billing_customer_service = MagicMock()
        billing_customer_service.get_effective_profile = AsyncMock(return_value=billing_profile)

        result = await mod.reader_user_me(
            db=AsyncMock(),
            current_user=current_user,
            billing_customer_service=billing_customer_service,
        )

        assert result.subscription_plan == "pro"
        assert result.subscription_status == "active"
        billing_customer_service.get_effective_profile.assert_awaited_once()


# ---------------------------------------------------------------------------
# OIDC verification tests
# ---------------------------------------------------------------------------


def _get_oidc_verify_module():
    """Get the ii_agent.auth.oidc_verify module."""
    import ii_agent.auth  # noqa

    return sys.modules.get("ii_agent.auth.oidc_verify")


class TestOidcVerifyR4:
    def test_fetch_discovery_raises_on_non_200(self):
        from ii_agent.auth.oidc_verify import fetch_discovery
        from ii_agent.auth.exceptions import OIDCConfigError

        oidc_mod = sys.modules["ii_agent.auth.oidc_verify"]
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(oidc_mod, "_get_http") as mock_http_factory:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get = MagicMock(return_value=mock_response)
            mock_http_factory.return_value = mock_client

            with pytest.raises(OIDCConfigError, match="Discovery fetch failed"):
                fetch_discovery("https://auth.example.com")

    def test_fetch_discovery_returns_json_on_200(self):
        from ii_agent.auth.oidc_verify import fetch_discovery

        oidc_mod = sys.modules["ii_agent.auth.oidc_verify"]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
            "issuer": "https://auth.example.com",
        }

        with patch.object(oidc_mod, "_get_http") as mock_http_factory:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get = MagicMock(return_value=mock_response)
            mock_http_factory.return_value = mock_client

            result = fetch_discovery("https://auth.example.com")
        assert "jwks_uri" in result

    def test_verify_at_hash_no_at_hash_returns_none(self):
        from ii_agent.auth.oidc_verify import verify_at_hash_if_present

        claims = {"sub": "user-1"}
        # Should not raise
        verify_at_hash_if_present(claims, "access-token")

    def test_verify_at_hash_no_access_token_returns_none(self):
        from ii_agent.auth.oidc_verify import verify_at_hash_if_present

        claims = {"at_hash": "abc123"}
        # Should not raise
        verify_at_hash_if_present(claims, None)

    def test_verify_at_hash_matching_hash_does_not_raise(self):
        from ii_agent.auth.oidc_verify import verify_at_hash_if_present

        access_token = "test-access-token"
        digest = hashlib.sha256(access_token.encode("ascii")).digest()
        left_half = digest[: len(digest) // 2]
        at_hash = base64.urlsafe_b64encode(left_half).rstrip(b"=").decode("ascii")
        claims = {"at_hash": at_hash}
        # Should not raise
        verify_at_hash_if_present(claims, access_token, alg="RS256")

    def test_verify_at_hash_mismatched_raises(self):
        from ii_agent.auth.oidc_verify import verify_at_hash_if_present

        claims = {"at_hash": "wrong-hash-value"}
        with pytest.raises(RuntimeError, match="at_hash mismatch"):
            verify_at_hash_if_present(claims, "access-token", alg="RS256")

    def test_verify_id_token_missing_jwks_uri_raises(self):
        from ii_agent.auth.oidc_verify import verify_id_token_pyjwt
        from ii_agent.auth.exceptions import OIDCConfigError

        oidc_mod = sys.modules["ii_agent.auth.oidc_verify"]

        with patch.object(oidc_mod, "fetch_discovery") as mock_disc:
            mock_disc.return_value = {}  # No jwks_uri
            with pytest.raises(OIDCConfigError, match="jwks_uri missing"):
                verify_id_token_pyjwt(
                    id_token="fake.token.here",
                    issuer="https://auth.example.com",
                    audience="client-id",
                )

    def test_verify_id_token_invalid_jwt_raises_runtime(self):
        from ii_agent.auth.oidc_verify import verify_id_token_pyjwt

        oidc_mod = sys.modules["ii_agent.auth.oidc_verify"]

        with (
            patch.object(oidc_mod, "fetch_discovery") as mock_disc,
            patch.object(oidc_mod, "_jwks_client") as mock_jwks_client,
        ):
            mock_disc.return_value = {"jwks_uri": "https://auth.example.com/jwks"}
            mock_client_inst = MagicMock()
            mock_client_inst.get_signing_key_from_jwt.side_effect = Exception("bad token")
            mock_jwks_client.return_value = mock_client_inst

            with pytest.raises(Exception):
                verify_id_token_pyjwt(
                    id_token="invalid.jwt.token",
                    issuer="https://auth.example.com",
                    audience="client-id",
                )

    def test_verify_id_token_nonce_mismatch_raises(self):
        from ii_agent.auth.oidc_verify import verify_id_token_pyjwt

        oidc_mod = sys.modules["ii_agent.auth.oidc_verify"]

        with (
            patch.object(oidc_mod, "fetch_discovery") as mock_disc,
            patch.object(oidc_mod, "_jwks_client") as mock_jwks_client,
            patch.object(oidc_mod, "jwt") as mock_jwt,
        ):
            mock_disc.return_value = {
                "jwks_uri": "https://auth.example.com/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            }
            mock_key = MagicMock()
            mock_key.key = "fake-key"
            mock_client_inst = MagicMock()
            mock_client_inst.get_signing_key_from_jwt.return_value = mock_key
            mock_jwks_client.return_value = mock_client_inst

            # Return claims with different nonce
            mock_jwt.decode.return_value = {"nonce": "other-nonce", "sub": "user-1"}

            with pytest.raises(RuntimeError, match="Invalid nonce"):
                verify_id_token_pyjwt(
                    id_token="valid.jwt.token",
                    issuer="https://auth.example.com",
                    audience="client-id",
                    expected_nonce="expected-nonce",
                )
