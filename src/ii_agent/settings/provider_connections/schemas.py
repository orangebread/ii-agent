"""Schemas for provider connection settings."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProviderConnectionStatus(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    REAUTH_REQUIRED = "reauth_required"
    REVOKED = "revoked"
    ERROR = "error"


class ProviderConnectionInfo(BaseModel):
    """Redacted provider connection information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    provider: str
    product: str
    auth_mode: Optional[str] = None
    external_account_id: Optional[str] = None
    display_name: Optional[str] = None
    scopes: Optional[dict[str, Any]] = None
    expires_at: Optional[datetime] = None
    last_refreshed_at: Optional[datetime] = None
    status: str
    last_error: Optional[str] = None
    connection_metadata: Optional[dict[str, Any]] = None
    has_credentials: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProviderConnectionList(BaseModel):
    """List wrapper for provider connection settings."""

    connections: list[ProviderConnectionInfo]
