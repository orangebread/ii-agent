"""Service layer for mcp_settings domain - business logic only."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi.encoders import jsonable_encoder
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.config.mcp import MCPSettings
from ii_agent.core.config.settings import Settings
from ii_agent.core.secrets.encryption import encryption_manager
from ii_agent.sessions.repository import SessionRepository
from ii_agent.settings.mcp.exceptions import MCPOAuthError, MCPSettingNotFoundError
from ii_agent.settings.mcp.models import MCPSetting
from ii_agent.settings.mcp.repository import MCPSettingRepository
from ii_agent.settings.mcp.schemas import (
    ClaudeCodeMetadata,
    ClaudeCodeOAuthStartResponse,
    CodexMetadata,
    MCPDefaultSelectionInfo,
    CodexOpenAIDevicePollResponse,
    CodexOpenAIDeviceStartResponse,
    MCPServersConfig,
    MCPSettingCreate,
    MCPSettingInfo,
    MCPSettingList,
    MCPSettingUpdate,
    validate_metadata,
)
from ii_agent.settings.provider_connections.service import ProviderConnectionService
from ii_agent.users.repository import UserRepository

OPENAI_DEVICE_CODE_TTL_SECONDS = 15 * 60
CLAUDE_CODE_OAUTH_SALT = "claude-code-oauth"
CLAUDE_CODE_OAUTH_SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)


class MCPSettingService:
    """Service for managing MCP settings - business logic layer."""

    def __init__(
        self,
        *,
        repo: MCPSettingRepository,
        config: Settings,
        user_repo: UserRepository | None = None,
        session_repo: SessionRepository | None = None,
        provider_connection_service: ProviderConnectionService | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._user_repo = user_repo
        self._session_repo = session_repo
        self._provider_connection_service = provider_connection_service

    async def create_mcp_settings(
        self, db: AsyncSession, *, mcp_setting_in: MCPSettingCreate, user_id: uuid.UUID
    ) -> MCPSettingInfo:
        """Create new MCP settings for a user."""
        new_setting = MCPSetting(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider_connection_id=_extract_provider_connection_id(mcp_setting_in.metadata),
            mcp_config=mcp_setting_in.mcp_config.model_dump(exclude_none=True),
            mcp_metadata=_metadata_to_storage_payload(mcp_setting_in.metadata),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        created = await self._repo.create(db, new_setting)
        return await self._serialize_setting_info(db, setting=created)

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
            setting.mcp_metadata = _metadata_to_storage_payload(setting_update.metadata)
            setting.provider_connection_id = _extract_provider_connection_id(
                setting_update.metadata
            )
        if setting_update.is_active is not None:
            setting.is_active = setting_update.is_active

        setting.updated_at = datetime.now(timezone.utc)
        updated = await self._repo.update(db, setting)
        return await self._serialize_setting_info(db, setting=updated)

    async def get_mcp_settings(
        self, db: AsyncSession, *, setting_id: str, user_id: uuid.UUID
    ) -> MCPSettingInfo:
        """Get MCP settings by ID."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting:
            raise MCPSettingNotFoundError(f"MCP setting {setting_id} not found or access denied")
        return await self._serialize_setting_info(db, setting=setting)

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
        settings_list = [
            await self._serialize_setting_info(
                db,
                setting=s,
                include_secrets=include_secrets,
            )
            for s in settings
        ]
        return MCPSettingList(settings=settings_list)

    async def delete_mcp_settings(
        self, db: AsyncSession, *, setting_id: str, user_id: uuid.UUID
    ) -> bool:
        """Delete MCP settings by ID."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting:
            return False
        provider_connection_id = setting.provider_connection_id

        await self._clear_runtime_selection_references(
            db,
            user_id=user_id,
            setting_id=setting.id,
        )
        await self._repo.delete(db, setting)
        await self._delete_orphaned_provider_connection(
            db,
            user_id=user_id,
            provider_connection_id=provider_connection_id,
        )
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
        return await self._serialize_setting_info(
            db,
            setting=setting,
            include_secrets=include_secrets,
        )

    async def get_claude_code_setting(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> Optional[MCPSettingInfo]:
        """Return the Claude Code MCP setting for a user, or None."""
        setting = await self._repo.get_by_user_and_tool_type(db, user_id, "claude_code")
        if not setting:
            return None
        return await self._serialize_setting_info(db, setting=setting)

    async def delete_claude_code_setting(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete the user's Claude Code MCP setting and its orphaned credentials."""
        setting = await self._repo.get_by_user_and_tool_type(db, user_id, "claude_code")
        if not setting:
            return False
        return await self.delete_mcp_settings(db, setting_id=setting.id, user_id=user_id)

    async def get_default_selection_info(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
    ) -> MCPDefaultSelectionInfo:
        """Return the user's current default MCP runtime selection."""
        user = await self._require_user_repo().get_by_id(db, user_id)
        return MCPDefaultSelectionInfo(
            default_mcp_setting_id=getattr(user, "default_mcp_setting_id", None) if user else None
        )

    async def set_default_runtime_setting(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        setting_id: uuid.UUID | None,
    ) -> MCPDefaultSelectionInfo:
        """Set or clear the user's default MCP runtime selection."""
        user_repo = self._require_user_repo()
        user = await user_repo.get_by_id(db, user_id)
        if user is None:
            raise MCPSettingNotFoundError(f"User {user_id} not found")

        if setting_id is not None:
            await self.assert_runtime_setting_selectable(
                db,
                user_id=user_id,
                setting_id=setting_id,
                selection_kind="default",
            )

        await user_repo.set_default_mcp_setting_id(db, user, setting_id)
        return MCPDefaultSelectionInfo(default_mcp_setting_id=setting_id)

    async def assert_runtime_setting_selectable(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        setting_id: uuid.UUID,
        selection_kind: str = "runtime",
    ) -> MCPSetting:
        """Validate that a runtime setting can be selected for use."""
        setting = await self._repo.get_by_id_and_user(db, setting_id, user_id)
        if not setting or not _is_runtime_setting(setting):
            raise MCPSettingNotFoundError(f"MCP setting {setting_id} not found or access denied")
        if not setting.is_active:
            raise MCPOAuthError(f"{selection_kind.capitalize()} MCP runtime must be active")
        if not await self._setting_has_provider_credentials(
            db,
            user_id=user_id,
            setting=setting,
        ):
            raise MCPOAuthError(
                f"{selection_kind.capitalize()} MCP runtime is missing provider credentials"
            )
        return setting

    async def resolve_effective_runtime_setting(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        session_id: uuid.UUID | None = None,
    ) -> Optional[MCPSetting]:
        """Resolve the runtime setting selected for a session or user."""
        session_repo = self._require_session_repo()
        user_repo = self._require_user_repo()

        if session_id is not None:
            session = await session_repo.get_by_id(db, session_id)
            if session and getattr(session, "mcp_setting_id", None):
                session_setting = await self._repo.get_by_id_and_user(
                    db,
                    session.mcp_setting_id,
                    user_id,
                )
                if session_setting and await self._is_usable_runtime_setting(
                    db,
                    user_id=user_id,
                    setting=session_setting,
                ):
                    return session_setting

        user = await user_repo.get_by_id(db, user_id)
        if user and getattr(user, "default_mcp_setting_id", None):
            default_setting = await self._repo.get_by_id_and_user(
                db,
                user.default_mcp_setting_id,
                user_id,
            )
            if default_setting and await self._is_usable_runtime_setting(
                db,
                user_id=user_id,
                setting=default_setting,
            ):
                return default_setting

        runtime_settings = await self._repo.list_runtime_settings_by_user(
            db,
            user_id,
            only_active=True,
        )
        preferred_runtime_settings = sorted(
            runtime_settings,
            key=lambda setting: 0 if _tool_type(setting) == "codex" else 1,
        )
        for setting in preferred_runtime_settings:
            if await self._is_usable_runtime_setting(
                db,
                user_id=user_id,
                setting=setting,
            ):
                return setting
        return None

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
        existing_auth_json: Optional[Dict[str, Any]] = None
        if (
            existing
            and getattr(existing, "provider_connection_id", None)
            and self._provider_connection_service is not None
        ):
            existing_connection = await self._provider_connection_service.get_connection_model(
                db,
                connection_id=getattr(existing, "provider_connection_id"),
                user_id=user_id,
            )
            if existing_connection:
                existing_auth_json = self._provider_connection_service.get_credentials_dict(
                    existing_connection
                )
        resolved_auth_json, auth_mode = _resolve_codex_auth(
            auth_json=auth_json,
            apikey=apikey,
            existing_auth_json=existing_auth_json or _extract_codex_auth_json(existing_metadata),
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
        claims = _extract_openai_auth_claims(resolved_auth_json)
        connected_at = (
            (existing_metadata or {}).get("oauth_connected_at")
            if auth_mode == "openai_oauth"
            else None
        ) or datetime.now(timezone.utc).isoformat()
        provider_connection = await self._require_provider_connection_service().upsert_connection(
            db,
            user_id=user_id,
            provider="openai",
            product="codex",
            credentials=resolved_auth_json,
            auth_mode=auth_mode,
            external_account_id=claims.get("chatgpt_account_id"),
            display_name="Codex",
            connection_metadata={
                "chatgpt_plan_type": claims.get("chatgpt_plan_type"),
                "chatgpt_account_id": claims.get("chatgpt_account_id"),
                "oauth_connected_at": connected_at if auth_mode == "openai_oauth" else None,
            },
        )
        metadata = CodexMetadata.model_validate(
            _build_codex_metadata(
                auth_mode=auth_mode,
                model=model,
                reasoning_effort=reasoning_effort,
                search=search,
                previous_metadata=existing_metadata,
                provider_connection_id=provider_connection.id,
                connection_metadata=provider_connection.connection_metadata or {},
            )
        )

        setting = await self._upsert_by_metadata_type(
            db,
            user_id=user_id,
            mcp_config=mcp_config,
            metadata=metadata,
        )
        if self._user_repo is not None:
            await self.set_default_runtime_setting(db, user_id=user_id, setting_id=setting.id)
        refreshed_setting = await self._repo.get_by_id_and_user(db, setting.id, user_id)
        if refreshed_setting is None:
            raise MCPSettingNotFoundError(f"MCP setting {setting.id} not found or access denied")
        return await self._serialize_setting_info(db, setting=refreshed_setting)

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

    async def start_claude_code_oauth(
        self,
        *,
        user_id: uuid.UUID,
        redirect_uri: str,
    ) -> ClaudeCodeOAuthStartResponse:
        """Create the Claude Code OAuth authorization URL for the authenticated user."""
        sanitized_redirect_uri = _sanitize_claude_code_redirect_uri(self._config, redirect_uri)
        verifier, challenge = _generate_pkce_pair()
        login_id = _create_claude_code_oauth_login_id(
            self._config,
            user_id=str(user_id),
            verifier=verifier,
            redirect_uri=sanitized_redirect_uri,
            oauth_redirect_uri=self._config.mcp.anthropic_oauth_redirect_uri,
        )
        auth_params = urlencode(
            {
                "code": "true",
                "client_id": self._config.mcp.anthropic_oauth_client_id,
                "response_type": "code",
                "redirect_uri": self._config.mcp.anthropic_oauth_redirect_uri,
                "scope": CLAUDE_CODE_OAUTH_SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": login_id,
            }
        )
        authorization_url = (
            f"{self._config.mcp.anthropic_oauth_authorize_url.rstrip('/')}?{auth_params}"
        )
        return ClaudeCodeOAuthStartResponse(
            login_id=login_id,
            authorization_url=authorization_url,
        )

    async def complete_claude_code_oauth(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        login_id: str,
        code: str,
        state: str,
    ) -> MCPSettingInfo:
        """Complete the Claude Code OAuth flow and persist the MCP setting."""
        login_state = _verify_claude_code_oauth_login_id(
            self._config,
            login_id,
            expected_user_id=str(user_id),
        )
        if state != login_id:
            raise MCPOAuthError("Anthropic OAuth state mismatch. Start the Claude login again.")

        return await self._configure_claude_code_with_code_and_verifier(
            db,
            user_id=user_id,
            code=code,
            verifier=login_state["verifier"],
            redirect_uri=login_state.get("oauth_redirect_uri")
            or self._config.mcp.anthropic_oauth_redirect_uri,
        )

    def resolve_claude_code_oauth_callback_redirect(
        self,
        *,
        state: str,
        code: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> str:
        """Resolve the frontend callback URL for the Claude Code OAuth popup."""
        login_state = _verify_claude_code_oauth_login_id(self._config, state)
        frontend_redirect_uri = login_state["redirect_uri"]

        params: dict[str, str] = {"state": state}
        if code:
            params["code"] = code
        if error:
            params["error"] = error
        if error_description:
            params["error_description"] = error_description

        return _append_query_params(frontend_redirect_uri, params)

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
        return await self._configure_claude_code_with_code_and_verifier(
            db,
            user_id=user_id,
            code=code,
            verifier=verifier,
            redirect_uri=self._config.mcp.anthropic_oauth_redirect_uri,
        )

    async def _configure_claude_code_with_code_and_verifier(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        code: str,
        verifier: str,
        redirect_uri: str,
    ) -> MCPSettingInfo:
        """Exchange OAuth code, build Claude Code MCP config and create-or-update."""
        tokens = await _exchange_code_for_tokens(
            code,
            verifier,
            self._config.mcp,
            redirect_uri=redirect_uri,
        )

        auth_json = {
            "claudeAiOauth": {
                "accessToken": tokens["access_token"],
                "refreshToken": tokens["refresh_token"],
                "expiresAt": int(time.time() * 1000) + tokens["expires_in"] * 1000,
                "scopes": ["user:inference", "user:profile"],
            }
        }
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
        provider_connection = await self._require_provider_connection_service().upsert_connection(
            db,
            user_id=user_id,
            provider="anthropic",
            product="claude_code",
            credentials=auth_json,
            auth_mode="anthropic_oauth",
            display_name="Claude Code",
            scopes={"values": ["user:inference", "user:profile"]},
            expires_at=expires_at,
            connection_metadata={"oauth_connected_at": datetime.now(timezone.utc).isoformat()},
        )
        metadata = ClaudeCodeMetadata(
            provider_connection_id=provider_connection.id,
            has_auth=True,
            store_path="~/.claude",
        )

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

        setting = await self._upsert_by_metadata_type(
            db,
            user_id=user_id,
            mcp_config=mcp_config,
            metadata=metadata,
        )
        if self._user_repo is not None:
            await self.set_default_runtime_setting(db, user_id=user_id, setting_id=setting.id)
        refreshed_setting = await self._repo.get_by_id_and_user(db, setting.id, user_id)
        if refreshed_setting is None:
            raise MCPSettingNotFoundError(f"MCP setting {setting.id} not found or access denied")
        return await self._serialize_setting_info(db, setting=refreshed_setting)

    async def _upsert_by_metadata_type(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
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

    def _require_user_repo(self) -> UserRepository:
        if self._user_repo is None:
            raise RuntimeError("UserRepository is required for runtime selection")
        return self._user_repo

    def _require_session_repo(self) -> SessionRepository:
        if self._session_repo is None:
            raise RuntimeError("SessionRepository is required for runtime selection")
        return self._session_repo

    def _require_provider_connection_service(self) -> ProviderConnectionService:
        if self._provider_connection_service is None:
            raise RuntimeError("ProviderConnectionService is required for provider auth storage")
        return self._provider_connection_service

    async def _clear_runtime_selection_references(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        setting_id: uuid.UUID,
    ) -> None:
        """Clear user/session runtime selections that point at a setting being deleted."""
        if self._user_repo is not None:
            user = await self._user_repo.get_by_id(db, user_id)
            if user and getattr(user, "default_mcp_setting_id", None) == setting_id:
                await self._user_repo.set_default_mcp_setting_id(db, user, None)

        if self._session_repo is not None:
            await self._session_repo.clear_mcp_setting_references(
                db,
                user_id=user_id,
                setting_id=setting_id,
            )

    async def _delete_orphaned_provider_connection(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        provider_connection_id: uuid.UUID | None,
    ) -> None:
        if provider_connection_id is None or self._provider_connection_service is None:
            return
        if await self._repo.has_provider_connection_reference(db, provider_connection_id):
            return
        await self._provider_connection_service.delete_connection(
            db,
            connection_id=provider_connection_id,
            user_id=user_id,
        )

    async def _is_usable_runtime_setting(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        setting: MCPSetting,
    ) -> bool:
        """Return whether a runtime setting is active, typed correctly, and has credentials."""
        return (
            setting.is_active
            and _is_runtime_setting(setting)
            and await self._setting_has_provider_credentials(
                db,
                user_id=user_id,
                setting=setting,
            )
        )

    async def _setting_has_provider_credentials(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        setting: MCPSetting,
    ) -> bool:
        """Return whether a runtime setting still has provider credentials available."""
        provider_connection_id = getattr(setting, "provider_connection_id", None)
        if not provider_connection_id:
            return False
        if self._provider_connection_service is None:
            return True

        connection = await self._provider_connection_service.get_connection_model(
            db,
            connection_id=provider_connection_id,
            user_id=user_id,
        )
        if connection is None:
            return False
        return self._provider_connection_service.has_usable_credentials(connection)

    async def _serialize_setting_info(
        self,
        db: AsyncSession,
        *,
        setting: MCPSetting,
        include_secrets: bool = False,
    ) -> MCPSettingInfo:
        info = _to_mcp_setting_info(setting, include_secrets=include_secrets)
        if _tool_type(setting) != "claude_code":
            return info
        return await self._hydrate_claude_code_setting_info(
            db,
            user_id=setting.user_id,
            setting=setting,
            info=info,
        )

    async def _hydrate_claude_code_setting_info(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        setting: MCPSetting,
        info: MCPSettingInfo,
    ) -> MCPSettingInfo:
        if not isinstance(info.metadata, ClaudeCodeMetadata):
            return info
        if self._provider_connection_service is None:
            return info

        auth_state = await self._get_provider_auth_state(
            db,
            user_id=user_id,
            provider_connection_id=getattr(setting, "provider_connection_id", None),
        )
        if auth_state is None:
            info.metadata = ClaudeCodeMetadata.model_validate(
                {
                    **info.metadata.model_dump(exclude_none=True),
                    "has_auth": False,
                    "auth_status": "missing",
                    "needs_reauth": True,
                }
            )
            return info

        info.metadata = ClaudeCodeMetadata.model_validate(
            {
                **info.metadata.model_dump(exclude_none=True),
                "has_auth": auth_state.is_usable,
                "auth_status": auth_state.auth_status,
                "needs_reauth": auth_state.needs_reauth,
            }
        )
        return info

    async def _get_provider_auth_state(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        provider_connection_id: uuid.UUID | None,
    ):
        if not provider_connection_id or self._provider_connection_service is None:
            return None

        connection = await self._provider_connection_service.get_connection_model(
            db,
            connection_id=provider_connection_id,
            user_id=user_id,
        )
        if connection is None:
            return None
        return self._provider_connection_service.describe_auth_state(connection)


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _get_claude_code_oauth_serializer(config: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(config.oauth.session_secret_key, salt=CLAUDE_CODE_OAUTH_SALT)


def _create_claude_code_oauth_login_id(
    config: Settings,
    *,
    user_id: str,
    verifier: str,
    redirect_uri: str,
    oauth_redirect_uri: str,
) -> str:
    return _get_claude_code_oauth_serializer(config).dumps(
        {
            "user_id": user_id,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "oauth_redirect_uri": oauth_redirect_uri,
            "expires_at": int(datetime.now(timezone.utc).timestamp())
            + OPENAI_DEVICE_CODE_TTL_SECONDS,
        }
    )


def _verify_claude_code_oauth_login_id(
    config: Settings,
    login_id: str,
    *,
    expected_user_id: str | None = None,
) -> dict[str, Any]:
    try:
        state = _get_claude_code_oauth_serializer(config).loads(login_id)
    except BadSignature as exc:
        raise MCPOAuthError("Invalid Claude Code OAuth state. Start again.") from exc

    if expected_user_id is not None and str(state.get("user_id") or "") != expected_user_id:
        raise MCPOAuthError("Claude Code OAuth state does not belong to this user.")
    if int(state.get("expires_at", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise MCPOAuthError("Claude Code OAuth expired. Start again.")
    return state


def _append_query_params(url: str, params: dict[str, str]) -> str:
    """Append query params to a URL while preserving existing query parameters."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _sanitize_claude_code_redirect_uri(config: Settings, redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MCPOAuthError("Claude Code redirect URI must be an absolute URL.")
    if parsed.path != "/claude-code-callback":
        raise MCPOAuthError("Claude Code redirect URI must use /claude-code-callback.")

    allowed_origins = set()
    frontend_origin = urlparse(config.ii_frontend_url)
    if frontend_origin.scheme and frontend_origin.netloc:
        allowed_origins.add(f"{frontend_origin.scheme}://{frontend_origin.netloc}")
    if config.environment == "local":
        allowed_origins.update(
            {
                "http://localhost:1420",
                "http://127.0.0.1:1420",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            }
        )

    redirect_origin = f"{parsed.scheme}://{parsed.netloc}"
    if redirect_origin not in allowed_origins:
        raise MCPOAuthError("Claude Code redirect URI origin is not allowed.")

    return redirect_uri


async def _exchange_code_for_tokens(
    code: str,
    verifier: str,
    mcp_config: MCPSettings,
    *,
    redirect_uri: str,
) -> dict:
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
                "redirect_uri": redirect_uri,
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
    existing_auth_json: Optional[Dict[str, Any]],
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

    if existing_auth_json:
        return existing_auth_json, _infer_codex_auth_mode(existing_auth_json)

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
    auth_mode: Optional[str],
    model: Optional[str],
    reasoning_effort: Optional[str],
    search: bool,
    previous_metadata: Optional[dict[str, Any]],
    provider_connection_id: uuid.UUID | str,
    connection_metadata: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build the stored/public Codex metadata payload."""
    resolved_auth_mode = auth_mode
    claims = connection_metadata or {}
    connected_at = (
        (previous_metadata or {}).get("oauth_connected_at")
        if resolved_auth_mode == "openai_oauth"
        else None
    ) or datetime.now(timezone.utc).isoformat()

    return {
        "tool_type": "codex",
        "store_path": "~/.codex",
        "has_auth": True,
        "provider_connection_id": provider_connection_id,
        "auth_mode": resolved_auth_mode,
        "oauth_provider": "openai" if resolved_auth_mode == "openai_oauth" else None,
        "oauth_connected_at": connected_at if resolved_auth_mode == "openai_oauth" else None,
        "chatgpt_plan_type": claims.get("chatgpt_plan_type"),
        "chatgpt_account_id": claims.get("chatgpt_account_id"),
        "model": model,
        "model_reasoning_effort": reasoning_effort,
        "search": search,
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
        processed["has_auth"] = bool(auth_json or processed.get("provider_connection_id"))
        if include_secrets and auth_json:
            processed["auth_json"] = auth_json
        else:
            processed.pop("auth_json", None)
        processed.pop("encrypted_auth_json", None)
    if processed.get("tool_type") == "claude_code":
        processed["has_auth"] = bool(processed.get("has_auth"))
        processed["needs_reauth"] = bool(processed.get("needs_reauth", False))
        processed.pop("auth_json", None)
    return processed


def _metadata_to_storage_payload(metadata: Any) -> dict[str, Any] | None:
    """Serialize metadata for DB storage while stripping deprecated secret fields."""
    if metadata is None:
        return None

    if hasattr(metadata, "model_dump"):
        payload = metadata.model_dump(mode="json", exclude_none=True)
    elif isinstance(metadata, dict):
        payload = jsonable_encoder(metadata, exclude_none=True)
    else:
        raise TypeError("Unsupported MCP metadata payload")

    if payload.get("tool_type") == "claude_code":
        payload.pop("auth_json", None)

    return payload


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


def _extract_provider_connection_id(metadata: Any) -> uuid.UUID | None:
    """Pull provider_connection_id from typed metadata when present."""
    if metadata is None:
        return None
    provider_connection_id = getattr(metadata, "provider_connection_id", None)
    if provider_connection_id is None and isinstance(metadata, dict):
        provider_connection_id = metadata.get("provider_connection_id")
    return provider_connection_id


def _tool_type(setting: MCPSetting) -> str | None:
    metadata = setting.mcp_metadata or {}
    if isinstance(metadata, dict):
        tool_type = metadata.get("tool_type")
        if isinstance(tool_type, str):
            return tool_type
    return None


def _is_runtime_setting(setting: MCPSetting) -> bool:
    return _tool_type(setting) in {"codex", "claude_code"}
