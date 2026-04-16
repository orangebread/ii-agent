"""Authentication API endpoints."""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_sso.sso.google import GoogleSSO
from itsdangerous import URLSafeSerializer, BadSignature

from ii_agent.auth.dependencies import DBSession, CurrentUser, SettingsDep
from ii_agent.auth.exceptions import AuthException, InvalidTokenException
from ii_agent.auth.jwt_handler import jwt_handler
from ii_agent.auth.oidc_verify import verify_id_token_pyjwt, verify_at_hash_if_present
from ii_agent.auth.schemas import (
    AuthProvidersResponse,
    OpenAIDevicePollRequest,
    OpenAIDevicePollResponse,
    OpenAIDeviceStartRequest,
    OpenAIDeviceStartResponse,
    TokenResponse,
)
from ii_agent.core.config.settings import get_settings
from ii_agent.core.exceptions import BadGatewayError, InternalError, ValidationError
from ii_agent.core.redis.cache import create_entity_cache
from ii_agent.core.secrets.encryption import encryption_manager
from ii_agent.settings.mcp.dependencies import MCPSettingServiceDep
from ii_agent.settings.mcp.exceptions import MCPOAuthError
from ii_agent.settings.mcp.service import (
    OPENAI_DEVICE_CODE_TTL_SECONDS,
    _build_openai_codex_auth_json,
    _exchange_openai_device_code,
    _poll_openai_device_code,
    _request_openai_device_code,
)
from ii_agent.users.dependencies import UserServiceDep
from ii_agent.users.exceptions import WaitlistDeniedException
from ii_agent.users.schemas import UserPublic

router = APIRouter(prefix="/auth", tags=["Authentication"])

II_STATE_SESSION_KEY = "ii_oauth_state"
II_CODE_VERIFIER_SESSION_KEY = "ii_code_verifier"
II_RETURN_TO_SESSION_KEY = "ii_return_to"
II_RETURN_URL_SESSION_KEY = "ii_return_url"
OPENAI_DEVICE_LOGIN_SALT = "auth-openai-device"
OPENAI_PENDING_CONNECT_STATE_SESSION_KEY = "openai_pending_connect_id"
OPENAI_PENDING_CONNECT_CACHE_NAMESPACE = "auth_openai_pending"
_openai_pending_connect_cache = None

# ---------------------------------------------------------------------------
# Auth callback HTML template (inlined from templates.py — single consumer)
# ---------------------------------------------------------------------------

_AUTH_CALLBACK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>II Login</title>
</head>
<body>
<script>
  (function() {
    const payload = %s;
    const targetOrigin = %s;
    const redirectUrl = %s;
    const message = { type: 'ii-auth-success', payload };
    const fallbackOrigin = (() => {
      if (targetOrigin) return targetOrigin;
      try {
        if (redirectUrl) return new URL(redirectUrl).origin;
      } catch (e) {}
      return window.location.origin;
    })();

    function redirectWithHash() {
      if (!redirectUrl) return;
      try {
        const url = new URL(redirectUrl);
        url.hash = 'ii-auth=' + encodeURIComponent(JSON.stringify(payload));
        window.location.replace(url.toString());
      } catch (e) {
        window.location.replace(redirectUrl);
      }
    }

    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(message, fallbackOrigin || '*');
        window.close();
        return;
      }
    } catch (err) {
      console.error('postMessage to opener failed', err);
    }

    if (redirectUrl) {
      redirectWithHash();
      return;
    }

    document.body.innerHTML = '<p>Login successful. You can close this window.</p>';
  })();
</script>
</body>
</html>
"""


def _render_auth_callback_html(
    token_payload: dict,
    return_origin: Optional[str],
    return_url: Optional[str],
) -> str:
    """Render the OAuth callback HTML that posts tokens back to the opener."""
    return _AUTH_CALLBACK_HTML % (
        json.dumps(token_payload),
        json.dumps(return_origin or ""),
        json.dumps(return_url or ""),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_serializer(salt: str = "ii-state") -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().oauth.session_secret_key, salt=salt)


def _make_state() -> str:
    raw = secrets.token_urlsafe(32)
    return _get_serializer().dumps(raw)


def _verify_state(value: str) -> bool:
    try:
        _get_serializer().loads(value)
        return True
    except BadSignature:
        return False


def _make_pkce_pair() -> tuple[str, str]:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _sanitize_return_to(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Invalid return_to parameter")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, value


def _extract_identity_from_pending_openai(
    pending_openai: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not pending_openai:
        return None

    auth_json = pending_openai.get("auth_json")
    if not isinstance(auth_json, dict):
        return None

    tokens = auth_json.get("tokens")
    if not isinstance(tokens, dict):
        return None

    id_token = tokens.get("id_token")
    if not isinstance(id_token, str) or "." not in id_token:
        return None

    identity = _extract_openai_identity(id_token)
    return identity if identity.get("email") else None


def _make_token_payload(user_id: str, email: str, role: str) -> dict:
    """Build the JWT token payload dict for a user."""
    access_token = jwt_handler.create_access_token(
        user_id=user_id,
        email=email,
        role=role,
    )
    refresh_token = jwt_handler.create_refresh_token(user_id=user_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": jwt_handler.access_token_expire_minutes * 60,
    }


async def _complete_dev_auth_bypass_login(
    *,
    db: DBSession,
    settings: SettingsDep,
    user_service: UserServiceDep,
    mcp_service: MCPSettingServiceDep,
    openai_pending: Optional[str],
    return_origin: Optional[str],
    return_url: Optional[str],
) -> HTMLResponse:
    pending_openai_id, pending_openai = await _get_pending_openai_connection(openai_pending)
    identity = _extract_identity_from_pending_openai(pending_openai)

    email = (
        str(identity.get("email") if identity else settings.dev_auth_bypass_email).strip().lower()
    )
    if not email:
        raise InternalError("DEV auth bypass email is not configured")

    first_name = str(
        identity.get("first_name") if identity else settings.dev_auth_bypass_first_name
    ).strip()
    last_name = str(
        identity.get("last_name") if identity else settings.dev_auth_bypass_last_name
    ).strip()
    avatar = identity.get("avatar") if identity else None
    email_verified = bool(identity.get("email_verified", True)) if identity else True

    user_stored = await user_service.find_or_create_oauth_user(
        db,
        email=email,
        first_name=first_name,
        last_name=last_name,
        avatar=avatar,
        email_verified=email_verified,
        login_provider="dev_bypass",
    )

    if pending_openai:
        await mcp_service.configure_codex(
            db,
            user_id=user_stored.id,
            auth_json=pending_openai["auth_json"],
            apikey=None,
            model=pending_openai.get("model"),
            reasoning_effort=pending_openai.get("reasoning_effort"),
            search=bool(pending_openai.get("search", False)),
        )
    if pending_openai_id:
        await _clear_pending_openai_connection(pending_openai_id)

    token_payload = _make_token_payload(
        str(user_stored.id),
        str(user_stored.email),
        str(user_stored.role),
    )
    html_content = _render_auth_callback_html(token_payload, return_origin, return_url)
    return HTMLResponse(content=html_content)


def _get_openai_device_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().oauth.session_secret_key, salt=OPENAI_DEVICE_LOGIN_SALT)


def _create_openai_device_login_id(
    *,
    device_code: dict[str, Any],
    model: Optional[str],
    reasoning_effort: Optional[str],
    search: bool,
) -> str:
    issued_at = int(datetime.now(timezone.utc).timestamp())
    return _get_openai_device_serializer().dumps(
        {
            "device_auth_id": device_code["device_auth_id"],
            "user_code": device_code["user_code"],
            "interval_seconds": device_code["interval_seconds"],
            "model": model,
            "reasoning_effort": reasoning_effort,
            "search": search,
            "issued_at": issued_at,
            "expires_at": issued_at + OPENAI_DEVICE_CODE_TTL_SECONDS,
        }
    )


def _verify_openai_device_login_id(login_id: str) -> dict[str, Any]:
    try:
        state = _get_openai_device_serializer().loads(login_id)
    except BadSignature as exc:
        raise ValidationError("Invalid OpenAI device login state") from exc

    if int(state.get("expires_at", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise ValidationError("OpenAI device login expired. Start again.")
    return state


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        return {}

    try:
        payload = token.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode()).decode()
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_openai_identity(id_token: str) -> dict[str, Any]:
    claims = _decode_jwt_payload(id_token)
    name = str(claims.get("name") or "").strip()
    first_name = str(claims.get("given_name") or "").strip()
    last_name = str(claims.get("family_name") or "").strip()

    if not first_name and name:
        parts = name.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    auth_claims = claims.get("https://api.openai.com/auth") or {}
    if not isinstance(auth_claims, dict):
        auth_claims = {}

    account_id = auth_claims.get("chatgpt_account_id") or claims.get("sub")
    email = str(claims.get("email") or "").strip().lower()
    if not email and account_id:
        email = f"openai-{account_id}@users.openai.local"

    return {
        "email": email,
        "email_verified": bool(claims.get("email_verified", False)),
        "first_name": first_name,
        "last_name": last_name,
        "avatar": claims.get("picture"),
        "account_id": account_id,
    }


def _is_synthetic_openai_email(email: str) -> bool:
    return email.endswith("@users.openai.local")


def _extract_ii_name_parts(claims: dict[str, Any]) -> tuple[str, str]:
    """Support either structured or flat ``name`` claims from the II IdP."""
    name_claim = claims.get("name")
    if isinstance(name_claim, dict):
        first_name = str(name_claim.get("first") or "").strip()
        last_name = str(name_claim.get("last") or "").strip()
        return first_name, last_name

    if isinstance(name_claim, str):
        parts = name_claim.strip().split()
        if not parts:
            return "", ""
        return parts[0], " ".join(parts[1:])

    return "", ""


def _get_openai_pending_connect_cache():
    global _openai_pending_connect_cache
    if _openai_pending_connect_cache is None:
        _openai_pending_connect_cache = create_entity_cache(
            namespace=OPENAI_PENDING_CONNECT_CACHE_NAMESPACE,
            ttl=OPENAI_DEVICE_CODE_TTL_SECONDS,
        )
    return _openai_pending_connect_cache


async def _stage_pending_openai_connection(
    *,
    auth_json: dict[str, Any],
    model: Optional[str],
    reasoning_effort: Optional[str],
    search: bool,
) -> str:
    pending_id = secrets.token_urlsafe(24)
    encrypted_auth_json = encryption_manager.encrypt(json.dumps(auth_json))
    cache = _get_openai_pending_connect_cache()

    await cache.set(
        pending_id,
        {
            "auth_json": encrypted_auth_json,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "search": search,
        },
        ttl=OPENAI_DEVICE_CODE_TTL_SECONDS,
    )
    return pending_id


async def _get_pending_openai_connection(
    pending_id: Optional[str],
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    if not pending_id:
        return pending_id, None
    cache = _get_openai_pending_connect_cache()
    payload = await cache.get(pending_id)
    if not isinstance(payload, dict):
        return pending_id, None

    decrypted_auth_json = encryption_manager.decrypt(str(payload.get("auth_json") or ""))
    if not decrypted_auth_json:
        return pending_id, None

    try:
        auth_json = json.loads(decrypted_auth_json)
    except json.JSONDecodeError:
        return pending_id, None

    return pending_id, {
        "auth_json": auth_json,
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "search": bool(payload.get("search", False)),
    }


async def _clear_pending_openai_connection(pending_id: Optional[str]) -> None:
    if pending_id:
        cache = _get_openai_pending_connect_cache()
        await cache.evict(pending_id)


async def _exchange_code_for_token(code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
    settings = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oauth.ii_redirect_uri,
        "client_id": settings.oauth.ii_client_id,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    headers = {"content-type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(settings.ii_token_url, data=data, headers=headers)
    if response.status_code != 200:
        raise BadGatewayError(f"Token exchange failed: {response.text}")
    return response.json()


async def _fetch_userinfo_if_enabled(
    access_token: Optional[str],
) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    if not access_token or not settings.oauth.ii_use_userinfo:
        return None

    url = settings.oauth.ii_userinfo_url
    if not url:
        async with httpx.AsyncClient(timeout=10) as client:
            discovery_resp = await client.get(
                f"{settings.ii_issuer}/.well-known/openid-configuration"
            )
        if discovery_resp.status_code != 200:
            raise BadGatewayError(
                f"Discovery fetch failed: {discovery_resp.status_code} {discovery_resp.text}"
            )
        url = discovery_resp.json().get("userinfo_endpoint")
        if not url:
            raise BadGatewayError("userinfo_endpoint missing in discovery document")

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise BadGatewayError(f"userinfo failed: {resp.text}")
    return resp.json()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/oauth/ii/login")
async def ii_login(
    request: Request,
    db: DBSession,
    settings: SettingsDep,
    user_service: UserServiceDep,
    mcp_service: MCPSettingServiceDep,
    return_to: Optional[str] = None,
    openai_pending: Optional[str] = None,
):
    """Initiate II OAuth login by redirecting to the authorization server."""

    origin, safe_url = _sanitize_return_to(return_to)
    if safe_url is None:
        referer = request.headers.get("referer")
        origin, safe_url = _sanitize_return_to(referer)

    if not settings.oauth.ii_client_id:
        if not settings.is_dev_auth_bypass_enabled:
            raise InternalError("II OAuth client_id not configured")
        return await _complete_dev_auth_bypass_login(
            db=db,
            settings=settings,
            user_service=user_service,
            mcp_service=mcp_service,
            openai_pending=openai_pending,
            return_origin=origin,
            return_url=safe_url,
        )

    state = _make_state()
    code_verifier, code_challenge = _make_pkce_pair()

    request.session[II_STATE_SESSION_KEY] = state
    request.session[II_CODE_VERIFIER_SESSION_KEY] = code_verifier
    if origin:
        request.session[II_RETURN_TO_SESSION_KEY] = origin
    if safe_url:
        request.session[II_RETURN_URL_SESSION_KEY] = safe_url
    if openai_pending:
        request.session[OPENAI_PENDING_CONNECT_STATE_SESSION_KEY] = openai_pending

    params = {
        "client_id": settings.oauth.ii_client_id,
        "response_type": "code",
        "redirect_uri": settings.oauth.ii_redirect_uri,
        "scope": settings.oauth.ii_scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    query = urlencode(params)
    return RedirectResponse(url=f"{settings.ii_auth_url}?{query}", status_code=302)


@router.get("/providers", response_model=AuthProvidersResponse)
async def auth_providers(settings: SettingsDep) -> AuthProvidersResponse:
    """Return public auth provider availability for the current environment."""
    ii_oauth_available = settings.oauth.has_ii_oauth() or settings.is_dev_auth_bypass_enabled
    return AuthProvidersResponse(
        ii_oauth_available=ii_oauth_available,
        google_oauth_available=settings.oauth.has_google_oauth(),
        dev_auth_bypass_enabled=settings.is_dev_auth_bypass_enabled,
    )


@router.get("/oauth/ii/callback")
async def ii_callback(
    request: Request,
    db: DBSession,
    settings: SettingsDep,
    user_service: UserServiceDep,
    mcp_service: MCPSettingServiceDep,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle II OAuth callback, verify tokens, and emit auth result."""

    if error:
        raise ValidationError(f"OAuth error: {error}")

    if not code or not state:
        raise ValidationError("Missing code or state")

    expected_state = request.session.get(II_STATE_SESSION_KEY)
    if not expected_state or state != expected_state or not _verify_state(state):
        raise ValidationError("Invalid state")

    code_verifier = request.session.get(II_CODE_VERIFIER_SESSION_KEY)

    token_set = await _exchange_code_for_token(code, code_verifier)

    id_token = token_set.get("id_token")
    hydra_access_token = token_set.get("access_token")

    if not id_token:
        raise BadGatewayError("Missing id_token in token response")

    try:
        claims = verify_id_token_pyjwt(
            id_token=id_token,
            issuer=settings.ii_issuer,
            audience=settings.oauth.ii_client_id,
            expected_nonce=None,
            leeway=60,
        )
        if hydra_access_token:
            verify_at_hash_if_present(claims, hydra_access_token, alg="RS256")
    except Exception as exc:  # noqa: BLE001
        raise InvalidTokenException(f"ID token verification failed: {exc}") from exc

    email_claim = claims.get("email")
    email = (email_claim or "").strip().lower()
    if not email:
        raise BadGatewayError("Email claim missing from ID token")

    email_verified = bool(claims.get("email_verified", False))
    first_name, last_name = _extract_ii_name_parts(claims)
    picture = claims.get("picture") or None

    userinfo = None
    try:
        userinfo = await _fetch_userinfo_if_enabled(hydra_access_token)
    except BadGatewayError:
        userinfo = None

    if userinfo:
        first_name = userinfo.get("given_name") or first_name
        last_name = userinfo.get("family_name") or last_name
        picture = userinfo.get("picture") or picture

    await user_service.check_waitlist(db, email)
    user_stored = await user_service.find_or_create_oauth_user(
        db,
        email=email,
        first_name=first_name,
        last_name=last_name,
        avatar=picture,
        email_verified=email_verified,
        login_provider="ii",
    )

    pending_openai_state = request.session.pop(OPENAI_PENDING_CONNECT_STATE_SESSION_KEY, None)
    pending_openai_id, pending_openai = await _get_pending_openai_connection(pending_openai_state)
    if pending_openai:
        await mcp_service.configure_codex(
            db,
            user_id=user_stored.id,
            auth_json=pending_openai["auth_json"],
            apikey=None,
            model=pending_openai.get("model"),
            reasoning_effort=pending_openai.get("reasoning_effort"),
            search=bool(pending_openai.get("search", False)),
        )
        await _clear_pending_openai_connection(pending_openai_id)
    elif pending_openai_id:
        await _clear_pending_openai_connection(pending_openai_id)

    token_payload = _make_token_payload(
        str(user_stored.id),
        str(user_stored.email),
        str(user_stored.role),
    )

    request.session.pop(II_STATE_SESSION_KEY, None)
    request.session.pop(II_CODE_VERIFIER_SESSION_KEY, None)

    return_origin = request.session.pop(II_RETURN_TO_SESSION_KEY, None)
    return_url = request.session.pop(II_RETURN_URL_SESSION_KEY, None)

    html_content = _render_auth_callback_html(token_payload, return_origin, return_url)
    return HTMLResponse(content=html_content)


@router.get("/oauth/google/login")
async def google_login(settings: SettingsDep):
    """Redirect to Google SSO login."""

    google_sso = GoogleSSO(
        settings.oauth.google_client_id or "",
        settings.oauth.google_client_secret or "",
        redirect_uri=settings.oauth.google_redirect_uri,
    )
    async with google_sso:
        return await google_sso.get_login_redirect(
            params={"prompt": "consent", "access_type": "offline"}
        )


@router.get("/oauth/google/callback")
async def google_callback(
    request: Request,
    db: DBSession,
    settings: SettingsDep,
    user_service: UserServiceDep,
):
    """Handle Google SSO callback and login."""
    state = request.query_params.get("state")
    if state:
        state_serializer = URLSafeSerializer(settings.oauth.session_secret_key)
        connector_state: Optional[dict[str, Any]] = None
        try:
            loaded_state = state_serializer.loads(state)
            if isinstance(loaded_state, dict):
                connector_state = loaded_state
        except BadSignature:
            connector_state = None

        if connector_state and connector_state.get("connector") == "google_drive":
            code = request.query_params.get("code")
            error = request.query_params.get("error")
            error_description = request.query_params.get("error_description")

            frontend_url = connector_state.get("frontend_url")
            if not frontend_url:
                referer = request.headers.get("referer")
                if referer:
                    parsed = urlparse(referer)
                    frontend_url = f"{parsed.scheme}://{parsed.netloc}"

            if not frontend_url:
                raise ValidationError("Could not determine frontend URL for redirect")

            params = {}
            if code:
                params["code"] = code
            if state:
                params["state"] = state
            if error:
                params["error"] = error
            if error_description:
                params["error_description"] = error_description

            query_string = urlencode(params)
            frontend_callback_url = f"{frontend_url}/google-drive-callback?{query_string}"

            return RedirectResponse(url=frontend_callback_url, status_code=302)

    url = request.query_params.get("redirect_uri")
    google_sso = GoogleSSO(
        settings.oauth.google_client_id or "",
        settings.oauth.google_client_secret or "",
        redirect_uri=(url or settings.oauth.google_redirect_uri),
    )
    async with google_sso:
        user_info = await google_sso.verify_and_process(request)
    if not user_info:
        raise AuthException("Failed to get user info from Google SSO")

    email = (user_info.email or "").strip().lower()
    if not email:
        raise ValidationError("Email not provided by Google account")

    bonus_credits = (
        settings.credits.beta_program_bonus_credits
        if settings.credits.beta_program_enabled
        else 0.0
    )
    await user_service.check_waitlist(db, email)
    user_stored = await user_service.find_or_create_oauth_user(
        db,
        email=email,
        first_name=user_info.first_name or "",
        last_name=user_info.last_name or "",
        avatar=user_info.picture or None,
        email_verified=True,
        bonus_credits=bonus_credits,
        login_provider="google",
    )

    token_payload = _make_token_payload(
        str(user_stored.id),
        str(user_stored.email),
        str(user_stored.role),
    )

    return TokenResponse(
        access_token=token_payload["access_token"],
        refresh_token=token_payload["refresh_token"],
        expires_in=token_payload["expires_in"],
    )


@router.post("/oauth/openai/device/start", response_model=OpenAIDeviceStartResponse)
async def start_openai_device_login(
    request: OpenAIDeviceStartRequest,
    settings: SettingsDep,
):
    """Start OpenAI device login and return the verification instructions."""
    device_code = await _request_openai_device_code(settings.mcp)
    login_id = _create_openai_device_login_id(
        device_code=device_code,
        model=request.model,
        reasoning_effort=request.model_reasoning_effort,
        search=request.search,
    )
    return OpenAIDeviceStartResponse(
        login_id=login_id,
        verification_url=device_code["verification_url"],
        user_code=device_code["user_code"],
        interval_seconds=device_code["interval_seconds"],
        expires_in_seconds=OPENAI_DEVICE_CODE_TTL_SECONDS,
    )


@router.post("/oauth/openai/device/poll", response_model=OpenAIDevicePollResponse)
async def poll_openai_device_login(
    payload: OpenAIDevicePollRequest,
    settings: SettingsDep,
):
    """Poll OpenAI device login and stage the Codex auth for the next II login."""
    try:
        login_state = _verify_openai_device_login_id(payload.login_id)
        code_payload = await _poll_openai_device_code(
            settings.mcp,
            device_auth_id=login_state["device_auth_id"],
            user_code=login_state["user_code"],
        )
        if code_payload is None:
            return OpenAIDevicePollResponse(status="pending", continue_with_ii=False)

        tokens = await _exchange_openai_device_code(
            settings.mcp,
            authorization_code=code_payload["authorization_code"],
            code_verifier=code_payload["code_verifier"],
        )
        auth_json = _build_openai_codex_auth_json(tokens)
        pending_connect_id = await _stage_pending_openai_connection(
            auth_json=auth_json,
            model=login_state.get("model"),
            reasoning_effort=login_state.get("reasoning_effort"),
            search=bool(login_state.get("search", False)),
        )
        return OpenAIDevicePollResponse(
            status="completed",
            continue_with_ii=True,
            pending_connect_id=pending_connect_id,
        )
    except (
        MCPOAuthError,
        ValidationError,
        WaitlistDeniedException,
        BadGatewayError,
    ) as exc:
        return OpenAIDevicePollResponse(
            status="error",
            continue_with_ii=False,
            error=str(exc),
        )


@router.get("/me", response_model=UserPublic)
async def reader_user_me(
    db: DBSession,
    current_user: CurrentUser,
) -> UserPublic:
    return UserPublic(
        id=str(current_user.id),
        email=str(current_user.email),
        role=str(current_user.role),
        first_name=str(current_user.first_name or ""),
        last_name=str(current_user.last_name or ""),
        avatar=current_user.avatar,
        subscription_status=current_user.subscription_status,
        subscription_plan=current_user.subscription_plan,
        subscription_billing_cycle=current_user.subscription_billing_cycle,
        subscription_current_period_end=current_user.subscription_current_period_end,
        language=str(current_user.language or "en"),
    )
