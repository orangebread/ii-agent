"""Service layer for mcp_settings domain - business logic only."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.config.mcp import MCPSettings
from ii_agent.core.config.settings import Settings
from ii_agent.core.secrets.encryption import encryption_manager
from ii_agent.settings.mcp.exceptions import MCPOAuthError, MCPSettingNotFoundError
from ii_agent.settings.mcp.models import MCPSetting
from ii_agent.settings.mcp.repository import MCPSettingRepository
from ii_agent.settings.mcp.schemas import (
    ClaudeCodeMetadata,
    CodexMetadata,
    CodexOpenAIDevicePollResponse,
    CodexOpenAIDeviceStartResponse,
    MCPServersConfig,
    MCPSettingCreate,
    MCPSettingInfo,
    MCPSettingList,
    MCPSettingUpdate,
    validate_metadata,
)

OPENAI_DEVICE_CODE_TTL_SECONDS = 15 * 60


class MCPSettingService:
    """Service for managing MCP settings - business logic layer."""

    def __init__(
        self,
        *,
        repo: MCPSettingRepository,
        config: Settings,
    ) -> None:
        self._config = config
        self._repo = repo

    async def create_mcp_settings(
        self, db: AsyncSession, *, mcp_setting_in: MCPSettingCreate, user_id: uuid.UUID
    ) -> MCPSettingInfo:
        """Create new MCP settings for a user."""
        active_settings = await self._repo.list_active_by_user(db, user_id)
        for setting in active_settings:
            setting.is_active = False
            setting.updated_at = datetime.now(timezone.utc)
            await self._repo.update(db, setting)

        new_setting = MCPSetting(
            id=str(uuid.uuid4()),
            user_id=user_id,
            mcp_config=mcp_setting_in.mcp_config.model_dump(exclude_none=True),
            mcp_metadata=None
            if not mcp_setting_in.metadata
            else mcp_setting_in.metadata.model_dump(exclude_none=True),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        created = await self._repo.create(db, new_setting)
        return _to_mcp_setting_info(created)

    async def update_mcp_settings(
        self,
        db: AsyncSession,
        *,
        setting_id: str,
        setting_update: MCPSettingUpdate,
        user_id: uuid.UUID,
    ) -> MCPSettingInfo:
        """Update existing MCP settings."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting:
            raise MCPSettingNotFoundError(f"MCP setting {setting_id} not found or access denied")

        if setting_update.mcp_config is not None:
            setting.mcp_config = setting_update.mcp_config.model_dump(exclude_none=True)
        if setting_update.metadata is not None:
            setting.mcp_metadata = setting_update.metadata.model_dump(exclude_none=True)
        if setting_update.is_active is not None:
            setting.is_active = setting_update.is_active

        setting.updated_at = datetime.now(timezone.utc)
        updated = await self._repo.update(db, setting)
        return _to_mcp_setting_info(updated)

    async def get_mcp_settings(
        self, db: AsyncSession, *, setting_id: str, user_id: uuid.UUID
    ) -> MCPSettingInfo:
        """Get MCP settings by ID."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting:
            raise MCPSettingNotFoundError(f"MCP setting {setting_id} not found or access denied")
        return _to_mcp_setting_info(setting)

    async def list_mcp_settings(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        only_active: bool = False,
        no_metadata: bool = False,
        include_secrets: bool = False,
    ) -> MCPSettingList:
        """List all MCP settings for a user."""
        settings = await self._repo.list_by_user(
            db, user_id, only_active=only_active, no_metadata=no_metadata
        )
        settings_list = [_to_mcp_setting_info(s, include_secrets=include_secrets) for s in settings]
        return MCPSettingList(settings=settings_list)

    async def delete_mcp_settings(
        self, db: AsyncSession, *, setting_id: str, user_id: uuid.UUID
    ) -> bool:
        """Delete MCP settings by ID."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting:
            return False

        await self._repo.delete(db, setting)
        return True

    async def get_codex_setting(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        include_secrets: bool = False,
    ) -> Optional[MCPSettingInfo]:
        """Return the Codex MCP setting for a user, or None."""
        setting = await self._repo.get_by_user_and_tool_type(db, user_id, "codex")
        if not setting:
            return None
        return _to_mcp_setting_info(setting, include_secrets=include_secrets)

    async def get_claude_code_setting(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> Optional[MCPSettingInfo]:
        """Return the Claude Code MCP setting for a user, or None."""
        setting = await self._repo.get_by_user_and_tool_type(db, user_id, "claude_code")
        if not setting:
            return None
        return _to_mcp_setting_info(setting)

    async def configure_codex(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        auth_json: Optional[Dict[str, Any]],
        apikey: Optional[str],
        model: Optional[str],
        reasoning_effort: Optional[str],
        search: bool,
    ) -> MCPSettingInfo:
        """Build Codex MCP config and create-or-update the setting."""
        existing = await self._repo.get_by_user_and_tool_type(db, user_id, "codex")
        existing_metadata = (
            existing.mcp_metadata if existing and isinstance(existing.mcp_metadata, dict) else None
        )
        resolved_auth_json, auth_mode = _resolve_codex_auth(
            auth_json=auth_json,
            apikey=apikey,
            existing_metadata=existing_metadata,
        )
        if not resolved_auth_json:
            raise MCPOAuthError("Authentication JSON or API Key is required")

        uvx_args = [
            "--from",
            "git+https://github.com/Intelligent-Internet/codex-as-mcp.git@main",
            "codex-as-mcp",
        ]
        server_args = ["--yolo"]
        if model:
            server_args.append(f"--model={model}")
        if reasoning_effort:
            server_args.append(f"--model_reasoning_effort={reasoning_effort}")
        if search:
            server_args.append("--search")

        mcp_config = MCPServersConfig.model_validate(
            {
                "mcpServers": {
                    "codex-as-mcp": {
                        "command": "uvx",
                        "type": "stdio",
                        "args": uvx_args + server_args,
                    }
                }
            }
        )
        metadata = CodexMetadata.model_validate(
            _build_codex_metadata(
                auth_json=resolved_auth_json,
                auth_mode=auth_mode,
                model=model,
                reasoning_effort=reasoning_effort,
                search=search,
                previous_metadata=existing_metadata,
            )
        )

        return await self._upsert_by_metadata_type(
            db,
            user_id=user_id,
            metadata_cls=CodexMetadata,
            mcp_config=mcp_config,
            metadata=metadata,
        )

    async def start_codex_openai_device_oauth(
        self,
        *,
        user_id: uuid.UUID,
        model: Optional[str],
        reasoning_effort: Optional[str],
        search: bool,
    ) -> CodexOpenAIDeviceStartResponse:
        """Start the OpenAI Codex device-code flow."""
        device_code = await _request_openai_device_code(self._config.mcp)
        login_id = _create_codex_openai_device_login_id(
            self._config,
            user_id=str(user_id),
            device_code=device_code,
            model=model,
            reasoning_effort=reasoning_effort,
            search=search,
        )
        return CodexOpenAIDeviceStartResponse(
            login_id=login_id,
            verification_url=device_code["verification_url"],
            user_code=device_code["user_code"],
            interval_seconds=device_code["interval_seconds"],
            expires_in_seconds=OPENAI_DEVICE_CODE_TTL_SECONDS,
        )

    async def poll_codex_openai_device_oauth(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        login_id: str,
    ) -> CodexOpenAIDevicePollResponse:
        """Poll the OpenAI Codex device-code flow and persist config when completed."""
        login_state = _verify_codex_openai_device_login_id(
            self._config,
            login_id,
            expected_user_id=str(user_id),
        )
        code_payload = await _poll_openai_device_code(
            self._config.mcp,
            device_auth_id=login_state["device_auth_id"],
            user_code=login_state["user_code"],
        )
        if code_payload is None:
            return CodexOpenAIDevicePollResponse(status="pending")

        tokens = await _exchange_openai_device_code(
            self._config.mcp,
            authorization_code=code_payload["authorization_code"],
            code_verifier=code_payload["code_verifier"],
        )
        auth_json = _build_openai_codex_auth_json(tokens)
        setting = await self.configure_codex(
            db,
            user_id=user_id,
            auth_json=auth_json,
            apikey=None,
            model=login_state.get("model"),
            reasoning_effort=login_state.get("reasoning_effort"),
            search=bool(login_state.get("search", False)),
        )
        return CodexOpenAIDevicePollResponse(status="completed", setting=setting)

    async def configure_claude_code(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        authorization_code: str,
    ) -> MCPSettingInfo:
        """Exchange OAuth code, build Claude Code MCP config and create-or-update."""
        splits = authorization_code.split("#")
        if len(splits) != 2:
            raise MCPOAuthError("Invalid authorization code format. Expected format: code#verifier")

        code, verifier = splits
        tokens = await _exchange_code_for_tokens(code, verifier, self._config.mcp)

        auth_json = {
            "claudeAiOauth": {
                "accessToken": tokens["access_token"],
                "refreshToken": tokens["refresh_token"],
                "expiresAt": int(time.time() * 1000) + tokens["expires_in"] * 1000,
                "scopes": ["user:inference", "user:profile"],
            }
        }
        metadata = ClaudeCodeMetadata(auth_json=auth_json, store_path="")  # pyright: ignore

        mcp_config = MCPServersConfig.model_validate(
            {
                "mcpServers": {
                    "claude-code-mcp": {
                        "command": "npx",
                        "args": ["-y", "@steipete/claude-code-mcp@latest"],
                    },
                }
            }
        )

        return await self._upsert_by_metadata_type(
            db,
            user_id=user_id,
            metadata_cls=ClaudeCodeMetadata,
            mcp_config=mcp_config,
            metadata=metadata,
        )

    async def _upsert_by_metadata_type(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        metadata_cls: type,
        mcp_config: MCPServersConfig,
        metadata: CodexMetadata | ClaudeCodeMetadata,
    ) -> MCPSettingInfo:
        """Find existing setting by metadata type and update, or create new."""
        existing = await self._repo.get_by_user_and_tool_type(db, user_id, metadata.tool_type)

        if existing:
            return await self.update_mcp_settings(
                db,
                setting_id=existing.id,
                setting_update=MCPSettingUpdate(
                    mcp_config=mcp_config, metadata=metadata, is_active=True
                ),
                user_id=user_id,
            )

        return await self.create_mcp_settings(
            db,
            mcp_setting_in=MCPSettingCreate(
                mcp_config=mcp_config,
                metadata=metadata,
            ),
            user_id=user_id,
        )


async def _exchange_code_for_tokens(code: str, verifier: str, mcp_config: MCPSettings) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            mcp_config.anthropic_oauth_token_url,
            headers={"Content-Type": "application/json"},
            json={
                "code": code,
                "state": verifier,
                "grant_type": "authorization_code",
                "client_id": mcp_config.anthropic_oauth_client_id,
                "redirect_uri": mcp_config.anthropic_oauth_redirect_uri,
                "code_verifier": verifier,
            },
        )

    if not response.is_success:
        raise MCPOAuthError(f"Failed to exchange authorization code for tokens: {response.text}")

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data["expires_in"],
    }


async def _request_openai_device_code(mcp_config: MCPSettings) -> dict[str, Any]:
    """Request a device code from OpenAI's auth service."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{mcp_config.openai_oauth_issuer.rstrip('/')}/api/accounts/deviceauth/usercode",
            headers={"Content-Type": "application/json"},
            json={"client_id": mcp_config.openai_oauth_client_id},
        )

    if not response.is_success:
        raise MCPOAuthError(f"Failed to start OpenAI device login: {response.text}")

    data = response.json()
    try:
        interval_seconds = int(str(data.get("interval", "5")).strip())
    except ValueError as exc:
        raise MCPOAuthError("OpenAI device login returned an invalid polling interval") from exc

    user_code = data.get("user_code") or data.get("usercode")
    if not user_code:
        raise MCPOAuthError("OpenAI device login did not return a user code")

    return {
        "device_auth_id": data["device_auth_id"],
        "user_code": user_code,
        "interval_seconds": interval_seconds,
        "verification_url": f"{mcp_config.openai_oauth_issuer.rstrip('/')}/codex/device",
    }


async def _poll_openai_device_code(
    mcp_config: MCPSettings,
    *,
    device_auth_id: str,
    user_code: str,
) -> Optional[dict[str, str]]:
    """Poll OpenAI's device-code endpoint until an authorization code is ready."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{mcp_config.openai_oauth_issuer.rstrip('/')}/api/accounts/deviceauth/token",
            headers={"Content-Type": "application/json"},
            json={"device_auth_id": device_auth_id, "user_code": user_code},
        )

    if response.status_code in {403, 404}:
        return None
    if not response.is_success:
        raise MCPOAuthError(f"OpenAI device login failed: {response.text}")

    data = response.json()
    return {
        "authorization_code": data["authorization_code"],
        "code_verifier": data["code_verifier"],
    }


async def _exchange_openai_device_code(
    mcp_config: MCPSettings,
    *,
    authorization_code: str,
    code_verifier: str,
) -> dict[str, str]:
    """Exchange an OpenAI device-code authorization code for tokens."""
    redirect_uri = f"{mcp_config.openai_oauth_issuer.rstrip('/')}/deviceauth/callback"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{mcp_config.openai_oauth_issuer.rstrip('/')}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": redirect_uri,
                "client_id": mcp_config.openai_oauth_client_id,
                "code_verifier": code_verifier,
            },
        )

    if not response.is_success:
        raise MCPOAuthError(f"Failed to exchange OpenAI device code: {response.text}")

    data = response.json()
    try:
        return {
            "id_token": data["id_token"],
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
        }
    except KeyError as exc:
        raise MCPOAuthError("OpenAI token exchange response was missing expected fields") from exc


def _resolve_codex_auth(
    *,
    auth_json: Optional[Dict[str, Any]],
    apikey: Optional[str],
    existing_metadata: Optional[dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolve Codex auth input while preserving existing credentials when appropriate."""
    if auth_json and apikey:
        merged_auth_json = dict(auth_json)
        merged_auth_json["OPENAI_API_KEY"] = apikey
        return merged_auth_json, "manual_auth_json"
    if auth_json:
        return auth_json, _infer_codex_auth_mode(auth_json)
    if apikey:
        return {"OPENAI_API_KEY": apikey}, "api_key"

    existing_auth_json = _extract_codex_auth_json(existing_metadata)
    if existing_auth_json:
        return existing_auth_json, str((existing_metadata or {}).get("auth_mode") or "")

    return None, None


def _infer_codex_auth_mode(auth_json: Dict[str, Any]) -> str:
    """Infer the Codex auth mode from an auth.json payload."""
    tokens = auth_json.get("tokens")
    if isinstance(tokens, dict) and tokens.get("refresh_token"):
        return "openai_oauth"
    if auth_json.get("OPENAI_API_KEY"):
        return "api_key"
    return "manual_auth_json"


def _extract_codex_auth_json(metadata: Optional[dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract Codex auth JSON from encrypted or legacy metadata."""
    if not metadata:
        return None

    encrypted_auth_json = metadata.get("encrypted_auth_json")
    if isinstance(encrypted_auth_json, str) and encrypted_auth_json:
        decrypted = encryption_manager.decrypt(encrypted_auth_json)
        if decrypted:
            try:
                return json.loads(decrypted)
            except json.JSONDecodeError:
                return None

    auth_json = metadata.get("auth_json")
    if isinstance(auth_json, dict):
        return auth_json
    if isinstance(auth_json, str):
        try:
            return json.loads(auth_json)
        except json.JSONDecodeError:
            return None
    return None


def _build_codex_metadata(
    *,
    auth_json: Dict[str, Any],
    auth_mode: Optional[str],
    model: Optional[str],
    reasoning_effort: Optional[str],
    search: bool,
    previous_metadata: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build the stored/public Codex metadata payload."""
    resolved_auth_mode = auth_mode or _infer_codex_auth_mode(auth_json)
    claims = _extract_openai_auth_claims(auth_json) if resolved_auth_mode == "openai_oauth" else {}
    connected_at = (
        (previous_metadata or {}).get("oauth_connected_at")
        if resolved_auth_mode == "openai_oauth"
        else None
    ) or datetime.now(timezone.utc).isoformat()

    return {
        "tool_type": "codex",
        "store_path": "~/.codex",
        "has_auth": True,
        "auth_mode": resolved_auth_mode,
        "oauth_provider": "openai" if resolved_auth_mode == "openai_oauth" else None,
        "oauth_connected_at": connected_at if resolved_auth_mode == "openai_oauth" else None,
        "chatgpt_plan_type": claims.get("chatgpt_plan_type"),
        "chatgpt_account_id": claims.get("chatgpt_account_id"),
        "model": model,
        "model_reasoning_effort": reasoning_effort,
        "search": search,
        "encrypted_auth_json": encryption_manager.encrypt(json.dumps(auth_json)),
    }


def _extract_openai_auth_claims(auth_json: Dict[str, Any]) -> dict[str, Optional[str]]:
    """Extract plan/account metadata from an OpenAI/Codex auth payload."""
    tokens = auth_json.get("tokens")
    if not isinstance(tokens, dict):
        return {"chatgpt_plan_type": None, "chatgpt_account_id": None}
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str) or "." not in id_token:
        return {
            "chatgpt_plan_type": None,
            "chatgpt_account_id": tokens.get("account_id"),
        }

    try:
        payload = id_token.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode()).decode()
        claims = json.loads(decoded)
    except Exception:
        return {
            "chatgpt_plan_type": None,
            "chatgpt_account_id": tokens.get("account_id"),
        }

    auth_claims = claims.get("https://api.openai.com/auth") or {}
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    return {
        "chatgpt_plan_type": auth_claims.get("chatgpt_plan_type"),
        "chatgpt_account_id": auth_claims.get("chatgpt_account_id") or tokens.get("account_id"),
    }


def _build_openai_codex_auth_json(tokens: dict[str, str]) -> dict[str, Any]:
    """Build the auth.json payload expected by Codex."""
    claims = _extract_openai_auth_claims({"tokens": {"id_token": tokens["id_token"]}})
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": tokens["id_token"],
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "account_id": claims.get("chatgpt_account_id"),
        },
        "last_refresh": datetime.now(timezone.utc).isoformat(),
    }


def _codex_openai_device_serializer(config: Settings) -> URLSafeSerializer:
    """Create a serializer for Codex OpenAI device login state."""
    return URLSafeSerializer(config.oauth.session_secret_key, salt="codex-openai-device")


def _create_codex_openai_device_login_id(
    config: Settings,
    *,
    user_id: str,
    device_code: dict[str, Any],
    model: Optional[str],
    reasoning_effort: Optional[str],
    search: bool,
) -> str:
    """Create a signed login identifier for a Codex OpenAI device-code flow."""
    issued_at = int(time.time())
    return _codex_openai_device_serializer(config).dumps(
        {
            "user_id": user_id,
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


def _verify_codex_openai_device_login_id(
    config: Settings,
    login_id: str,
    *,
    expected_user_id: str,
) -> dict[str, Any]:
    """Verify the signed login identifier for a Codex OpenAI device-code flow."""
    try:
        state = _codex_openai_device_serializer(config).loads(login_id)
    except BadSignature as exc:
        raise MCPOAuthError("Invalid OpenAI device login state") from exc

    if state.get("user_id") != expected_user_id:
        raise MCPOAuthError("Invalid OpenAI device login state")
    if int(state.get("expires_at", 0)) < int(time.time()):
        raise MCPOAuthError("OpenAI device login expired. Start again.")
    return state


def _normalize_metadata(
    metadata_dict: dict[str, Any],
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    """Normalize metadata for response serialization."""
    processed = dict(metadata_dict)
    if processed.get("tool_type") == "codex":
        auth_json = _extract_codex_auth_json(processed)
        processed["has_auth"] = bool(auth_json)
        if include_secrets and auth_json:
            processed["auth_json"] = auth_json
        else:
            processed.pop("auth_json", None)
        processed.pop("encrypted_auth_json", None)
    return processed


def _to_mcp_setting_info(setting: MCPSetting, *, include_secrets: bool = False) -> MCPSettingInfo:
    """Convert database model to Pydantic model."""
    mcp_config = setting.mcp_config or {}
    if isinstance(mcp_config, dict):
        mcp_config = MCPServersConfig(**mcp_config)

    metadata = None
    if setting.mcp_metadata is not None and isinstance(setting.mcp_metadata, dict):
        try:
            metadata = validate_metadata(
                _normalize_metadata(setting.mcp_metadata, include_secrets=include_secrets)
            )
        except (ValueError, TypeError):
            pass

    return MCPSettingInfo(
        id=setting.id,
        mcp_config=mcp_config,
        is_active=setting.is_active,
        metadata=metadata,
        created_at=setting.created_at.isoformat() if setting.created_at else "",
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
    )
