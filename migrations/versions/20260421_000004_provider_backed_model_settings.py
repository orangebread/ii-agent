"""Add provider-backed model setting linkage.

Revision ID: 20260421_000004
Revises: 20260416_000003
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260421_000004"
down_revision = "20260416_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_settings",
        sa.Column("provider_connection_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_model_settings_provider_connection_id",
        "model_settings",
        "provider_connections",
        ["provider_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_model_settings_provider_connection_id",
        "model_settings",
        ["provider_connection_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_model_settings_provider_connection_id", table_name="model_settings")
    op.drop_constraint(
        "fk_model_settings_provider_connection_id",
        "model_settings",
        type_="foreignkey",
    )
    op.drop_column("model_settings", "provider_connection_id")
