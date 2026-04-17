"""Add provider connections and explicit MCP runtime selection.

Revision ID: 20260416_000003
Revises: 20260402_000002
Create Date: 2026-04-16
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ii_agent.core.secrets.encryption import encryption_manager


revision = "20260416_000003"
down_revision = "20260402_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column(
            "id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("auth_mode", sa.String(), nullable=True),
        sa.Column("encrypted_credentials_json", sa.String(), nullable=False),
        sa.Column("external_account_id", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("scopes", JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="connected"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("idx_provider_connections_user_id", "provider_connections", ["user_id"])
    op.create_index("idx_provider_connections_provider", "provider_connections", ["provider"])
    op.create_index(
        "uq_provider_connections_user_provider_product",
        "provider_connections",
        ["user_id", "provider", "product"],
        unique=True,
    )

    op.add_column(
        "mcp_settings", sa.Column("provider_connection_id", UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_mcp_settings_provider_connection_id",
        "mcp_settings",
        "provider_connections",
        ["provider_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_mcp_settings_provider_connection_id", "mcp_settings", ["provider_connection_id"]
    )

    op.add_column("users", sa.Column("default_mcp_setting_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_users_default_mcp_setting_id",
        "users",
        "mcp_settings",
        ["default_mcp_setting_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_users_default_mcp_setting_id", "users", ["default_mcp_setting_id"])

    op.add_column("sessions", sa.Column("mcp_setting_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_sessions_mcp_setting_id",
        "sessions",
        "mcp_settings",
        ["mcp_setting_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_sessions_mcp_setting_id", "sessions", ["mcp_setting_id"])

    _backfill_provider_connections()


def downgrade() -> None:
    op.drop_index("idx_sessions_mcp_setting_id", table_name="sessions")
    op.drop_constraint("fk_sessions_mcp_setting_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "mcp_setting_id")

    op.drop_index("idx_users_default_mcp_setting_id", table_name="users")
    op.drop_constraint("fk_users_default_mcp_setting_id", "users", type_="foreignkey")
    op.drop_column("users", "default_mcp_setting_id")

    op.drop_index("idx_mcp_settings_provider_connection_id", table_name="mcp_settings")
    op.drop_constraint("fk_mcp_settings_provider_connection_id", "mcp_settings", type_="foreignkey")
    op.drop_column("mcp_settings", "provider_connection_id")

    op.drop_index(
        "uq_provider_connections_user_provider_product", table_name="provider_connections"
    )
    op.drop_index("idx_provider_connections_provider", table_name="provider_connections")
    op.drop_index("idx_provider_connections_user_id", table_name="provider_connections")
    op.drop_table("provider_connections")


def _backfill_provider_connections() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    mcp_settings = sa.Table(
        "mcp_settings",
        metadata,
        sa.Column("id", UUID(as_uuid=True)),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("provider_connection_id", UUID(as_uuid=True)),
        sa.Column("metadata", JSONB),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    provider_connections = sa.Table(
        "provider_connections",
        metadata,
        sa.Column("id", UUID(as_uuid=True)),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("provider", sa.String()),
        sa.Column("product", sa.String()),
        sa.Column("auth_mode", sa.String()),
        sa.Column("encrypted_credentials_json", sa.String()),
        sa.Column("external_account_id", sa.String()),
        sa.Column("display_name", sa.String()),
        sa.Column("scopes", JSONB),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String()),
        sa.Column("last_error", sa.String()),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", UUID(as_uuid=True)),
        sa.Column("default_mcp_setting_id", UUID(as_uuid=True)),
    )

    rows = connection.execute(
        sa.select(
            mcp_settings.c.id,
            mcp_settings.c.user_id,
            mcp_settings.c.metadata,
            mcp_settings.c.is_active,
            mcp_settings.c.created_at,
        ).order_by(
            sa.desc(mcp_settings.c.is_active),
            sa.desc(mcp_settings.c.created_at),
            sa.desc(mcp_settings.c.id),
        )
    ).mappings()

    active_runtime_by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
    provider_connection_ids_by_key: dict[tuple[uuid.UUID, str, str], uuid.UUID] = {}
    now = datetime.now(timezone.utc)

    for row in rows:
        raw_metadata = dict(row["metadata"] or {})
        tool_type = raw_metadata.get("tool_type")
        if tool_type not in {"codex", "claude_code"}:
            continue

        provider = "openai" if tool_type == "codex" else "anthropic"
        product = "codex" if tool_type == "codex" else "claude_code"
        auth_mode = raw_metadata.get("auth_mode") or (
            "anthropic_oauth" if tool_type == "claude_code" else None
        )
        expires_at = None
        scopes = None
        if tool_type == "codex":
            encrypted_credentials_json = raw_metadata.get("encrypted_auth_json")
            if not encrypted_credentials_json and raw_metadata.get("auth_json") is not None:
                encrypted_credentials_json = encryption_manager.encrypt(
                    json.dumps(raw_metadata.get("auth_json"))
                )
            connection_metadata = {
                "chatgpt_plan_type": raw_metadata.get("chatgpt_plan_type"),
                "chatgpt_account_id": raw_metadata.get("chatgpt_account_id"),
                "oauth_connected_at": raw_metadata.get("oauth_connected_at"),
            }
            external_account_id = raw_metadata.get("chatgpt_account_id")
            display_name = "Codex"
        else:
            auth_json = raw_metadata.get("auth_json") or {}
            if isinstance(auth_json, str):
                try:
                    auth_json = json.loads(auth_json)
                except json.JSONDecodeError:
                    auth_json = {}
            encrypted_credentials_json = encryption_manager.encrypt(json.dumps(auth_json))
            claude_oauth = auth_json.get("claudeAiOauth", {}) if isinstance(auth_json, dict) else {}
            expires_ms = claude_oauth.get("expiresAt")
            if isinstance(expires_ms, int):
                expires_at = datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
            scopes = {"values": claude_oauth.get("scopes", [])}
            connection_metadata = {
                "oauth_connected_at": now.isoformat(),
            }
            external_account_id = None
            display_name = "Claude Code"

        if not encrypted_credentials_json:
            continue

        connection_key = (row["user_id"], provider, product)
        connection_id = provider_connection_ids_by_key.get(connection_key)
        if connection_id is None:
            connection_id = uuid.uuid4()
            provider_connection_ids_by_key[connection_key] = connection_id
            connection.execute(
                provider_connections.insert().values(
                    id=connection_id,
                    user_id=row["user_id"],
                    provider=provider,
                    product=product,
                    auth_mode=auth_mode,
                    encrypted_credentials_json=encrypted_credentials_json,
                    external_account_id=external_account_id,
                    display_name=display_name,
                    scopes=scopes,
                    expires_at=expires_at,
                    last_refreshed_at=now,
                    status="connected",
                    last_error=None,
                    metadata=connection_metadata,
                    created_at=now,
                    updated_at=now,
                )
            )

        cleaned_metadata = dict(raw_metadata)
        cleaned_metadata.pop("auth_json", None)
        cleaned_metadata.pop("encrypted_auth_json", None)
        cleaned_metadata["provider_connection_id"] = str(connection_id)
        cleaned_metadata["has_auth"] = True

        connection.execute(
            mcp_settings.update()
            .where(mcp_settings.c.id == row["id"])
            .values(
                provider_connection_id=connection_id,
                metadata=cleaned_metadata,
            )
        )

        if row["is_active"]:
            active_runtime_by_user.setdefault(row["user_id"], []).append(row["id"])

    for user_id, setting_ids in active_runtime_by_user.items():
        if len(setting_ids) == 1:
            connection.execute(
                users.update()
                .where(users.c.id == user_id)
                .values(default_mcp_setting_id=setting_ids[0])
            )
