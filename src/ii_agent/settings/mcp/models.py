"""SQLAlchemy models for mcp_settings domain."""

import uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from ii_agent.core.db.base import Base, TimestampColumn

if TYPE_CHECKING:
    from ii_agent.users.models import User
    from ii_agent.settings.provider_connections.models import ProviderConnection


class MCPSetting(Base):
    """Database model for MCP (Model Context Protocol) settings."""

    __tablename__ = "mcp_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    mcp_config: Mapped[dict] = mapped_column(JSONB(none_as_null=True))
    mcp_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB(none_as_null=True), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TimestampColumn, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampColumn,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="mcp_settings",
        foreign_keys=[user_id],
    )
    provider_connection: Mapped[Optional["ProviderConnection"]] = relationship(
        "ProviderConnection",
        back_populates="mcp_settings",
    )
