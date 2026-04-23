"""SQLAlchemy models for llm_settings domain."""

import uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Boolean, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from typing import Literal, Optional, TYPE_CHECKING

from .types import Provider
from ii_agent.core.db.base import Base

if TYPE_CHECKING:
    from ii_agent.users.models import User
    from ii_agent.sessions.models import Session
    from ii_agent.settings.provider_connections.models import ProviderConnection


class ModelSetting(Base):
    """Database model for LLM model settings.

    Columns:
        model_id: Model identifier (e.g. "claude-sonnet-4-6", "gpt-4o").
        provider: Provider name (e.g. "Anthropic", "OpenAI", "Google", "Custom").
        encrypted_api_key: Encrypted API key for authentication.
        provider_connection_id: Optional provider-backed OAuth credential source.
        base_url: Custom base URL for API endpoints.
        display_name: Human-readable label shown in the UI.
        configs: JSONB bag for provider-specific settings (temperature, thinking_tokens,
                 max_retries, max_message_chars, vertex_region, azure_endpoint, etc.).
        pricing: JSONB storing PricingInfo data (input/output/cache prices per million tokens).
        config_type: "user" or "system" discriminator.
        is_default: Whether this is the default model for the user/system.
    """

    __tablename__ = "model_settings"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    model_id: Mapped[str] = mapped_column(String)
    provider: Mapped[Provider] = mapped_column(String)
    encrypted_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    provider_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    pricing: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    config_type: Mapped[Literal["system", "user"]] = mapped_column(String, default="user")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="model_settings")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="model_setting")
    provider_connection: Mapped[Optional["ProviderConnection"]] = relationship(
        "ProviderConnection",
        back_populates="model_settings",
    )

    # Indexes & constraints
    __table_args__ = (
        # User rows: one setting per (model_id, provider) per user
        Index(
            "uq_model_settings_user",
            "model_id",
            "provider",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # System rows: one setting per (model_id, provider) globally
        Index(
            "uq_model_settings_system",
            "model_id",
            "provider",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        Index("idx_model_settings_provider_connection_id", "provider_connection_id"),
    )
