"""Service layer for provider connection settings."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.secrets.encryption import encryption_manager
from ii_agent.settings.provider_connections.models import ProviderConnection
from ii_agent.settings.provider_connections.repository import ProviderConnectionRepository
from ii_agent.settings.provider_connections.schemas import (
    ProviderConnectionInfo,
    ProviderConnectionList,
    ProviderConnectionStatus,
)


@dataclass(frozen=True)
class ProviderConnectionAuthState:
    """Derived runtime auth state for a provider connection."""

    has_stored_auth: bool
    is_usable: bool
    auth_status: str
    needs_reauth: bool


class ProviderConnectionService:
    """Manage encrypted provider credentials separately from MCP runtime config."""

    def __init__(self, *, repo: ProviderConnectionRepository) -> None:
        self._repo = repo

    async def list_connections(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
    ) -> ProviderConnectionList:
        rows = await self._repo.list_by_user(db, user_id=user_id)
        return ProviderConnectionList(connections=[_to_info(row) for row in rows])

    async def get_connection(
        self,
        db: AsyncSession,
        *,
        connection_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[ProviderConnectionInfo]:
        row = await self._repo.get_by_id_and_user(db, connection_id, user_id)
        return _to_info(row) if row else None

    async def get_connection_model(
        self,
        db: AsyncSession,
        *,
        connection_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[ProviderConnection]:
        return await self._repo.get_by_id_and_user(db, connection_id, user_id)

    async def get_by_provider_product(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        provider: str,
        product: str,
    ) -> Optional[ProviderConnection]:
        return await self._repo.get_by_provider_product(
            db,
            user_id=user_id,
            provider=provider,
            product=product,
        )

    async def delete_connection(
        self,
        db: AsyncSession,
        *,
        connection_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> bool:
        row = await self._repo.get_by_id_and_user(db, connection_id, user_id)
        if row is None:
            return False
        await self._repo.delete(db, row)
        return True

    async def upsert_connection(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        provider: str,
        product: str,
        credentials: dict[str, Any] | None = None,
        encrypted_credentials_json: str | None = None,
        auth_mode: str | None = None,
        external_account_id: str | None = None,
        display_name: str | None = None,
        scopes: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        last_refreshed_at: datetime | None = None,
        status: str = ProviderConnectionStatus.CONNECTED.value,
        last_error: str | None = None,
        connection_metadata: dict[str, Any] | None = None,
    ) -> ProviderConnection:
        existing = await self._repo.get_by_provider_product(
            db,
            user_id=user_id,
            provider=provider,
            product=product,
        )
        payload = encrypted_credentials_json or encryption_manager.encrypt(
            json.dumps(credentials or {})
        )
        now = datetime.now(timezone.utc)

        if existing:
            existing.auth_mode = auth_mode
            existing.encrypted_credentials_json = payload
            existing.external_account_id = external_account_id
            existing.display_name = display_name
            existing.scopes = scopes
            existing.expires_at = expires_at
            existing.last_refreshed_at = last_refreshed_at or now
            existing.status = status
            existing.last_error = last_error
            existing.connection_metadata = connection_metadata
            existing.updated_at = now
            return await self._repo.update(db, existing)

        row = ProviderConnection(
            id=uuid.uuid4(),
            user_id=user_id,
            provider=provider,
            product=product,
            auth_mode=auth_mode,
            encrypted_credentials_json=payload,
            external_account_id=external_account_id,
            display_name=display_name,
            scopes=scopes,
            expires_at=expires_at,
            last_refreshed_at=last_refreshed_at or now,
            status=status,
            last_error=last_error,
            connection_metadata=connection_metadata,
            created_at=now,
            updated_at=now,
        )
        return await self._repo.create(db, row)

    def get_credentials_dict(self, connection: ProviderConnection) -> dict[str, Any]:
        decrypted = encryption_manager.decrypt(connection.encrypted_credentials_json)
        if not decrypted:
            return {}
        try:
            return json.loads(decrypted)
        except json.JSONDecodeError:
            return {}

    def has_usable_credentials(
        self,
        connection: ProviderConnection,
        *,
        now: datetime | None = None,
    ) -> bool:
        return self.describe_auth_state(connection, now=now).is_usable

    def describe_auth_state(
        self,
        connection: ProviderConnection,
        *,
        now: datetime | None = None,
    ) -> ProviderConnectionAuthState:
        current_time = now or datetime.now(timezone.utc)
        credentials = self.get_credentials_dict(connection)
        has_stored_auth = bool(credentials)
        status = getattr(connection, "status", None) or ProviderConnectionStatus.CONNECTED.value

        if not has_stored_auth:
            return ProviderConnectionAuthState(
                has_stored_auth=False,
                is_usable=False,
                auth_status="missing",
                needs_reauth=True,
            )

        if status != ProviderConnectionStatus.CONNECTED.value:
            return ProviderConnectionAuthState(
                has_stored_auth=True,
                is_usable=False,
                auth_status=status,
                needs_reauth=True,
            )

        if _has_refreshable_oauth_credentials(connection, credentials):
            return ProviderConnectionAuthState(
                has_stored_auth=True,
                is_usable=True,
                auth_status=ProviderConnectionStatus.CONNECTED.value,
                needs_reauth=False,
            )

        expires_at = getattr(connection, "expires_at", None)
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= current_time:
                return ProviderConnectionAuthState(
                    has_stored_auth=True,
                    is_usable=False,
                    auth_status=ProviderConnectionStatus.EXPIRED.value,
                    needs_reauth=True,
                )

        return ProviderConnectionAuthState(
            has_stored_auth=True,
            is_usable=True,
            auth_status=ProviderConnectionStatus.CONNECTED.value,
            needs_reauth=False,
        )


def _to_info(connection: ProviderConnection) -> ProviderConnectionInfo:
    return ProviderConnectionInfo(
        id=connection.id,
        user_id=connection.user_id,
        provider=connection.provider,
        product=connection.product,
        auth_mode=connection.auth_mode,
        external_account_id=connection.external_account_id,
        display_name=connection.display_name,
        scopes=connection.scopes,
        expires_at=connection.expires_at,
        last_refreshed_at=connection.last_refreshed_at,
        status=connection.status,
        last_error=connection.last_error,
        connection_metadata=connection.connection_metadata,
        has_credentials=bool(connection.encrypted_credentials_json),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _has_refreshable_oauth_credentials(
    connection: ProviderConnection,
    credentials: dict[str, Any],
) -> bool:
    """Return whether the stored credentials can self-refresh without reauth."""
    if (
        getattr(connection, "provider", None) == "anthropic"
        and getattr(connection, "product", None) == "claude_code"
    ):
        oauth = credentials.get("claudeAiOauth")
        return isinstance(oauth, dict) and bool(oauth.get("refreshToken"))

    tokens = credentials.get("tokens")
    return isinstance(tokens, dict) and bool(tokens.get("refresh_token"))
