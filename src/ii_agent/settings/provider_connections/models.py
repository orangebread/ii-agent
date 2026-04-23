"""SQLAlchemy models for provider connection settings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ii_agent.core.db.base import Base, TimestampColumn

if TYPE_CHECKING:
    from ii_agent.users.models import User
    from ii_agent.settings.mcp.models import MCPSetting
    from ii_agent.settings.llm.models import ModelSetting


class ProviderConnection(Base):
    """Encrypted credentials and metadata for a user/provider runtime connection."""

    __tablename__ = "provider_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    product: Mapped[str] = mapped_column(String, nullable=False)
    auth_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    encrypted_credentials_json: Mapped[str] = mapped_column(String, nullable=False)
    external_account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scopes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(TimestampColumn, nullable=True)
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(TimestampColumn, nullable=True)
    status: Mapped[str] = mapped_column(String, default="connected")
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    connection_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TimestampColumn, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampColumn,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="provider_connections")
    mcp_settings: Mapped[list["MCPSetting"]] = relationship(
        "MCPSetting",
        back_populates="provider_connection",
    )
    model_settings: Mapped[list["ModelSetting"]] = relationship(
        "ModelSetting",
        back_populates="provider_connection",
    )

    __table_args__ = (
        Index("idx_provider_connections_user_id", "user_id"),
        Index("idx_provider_connections_provider", "provider"),
        Index(
            "uq_provider_connections_user_provider_product",
            "user_id",
            "provider",
            "product",
            unique=True,
        ),
    )
