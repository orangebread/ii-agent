"""Repository layer for provider connection settings."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.db.base import BaseRepository
from ii_agent.settings.provider_connections.models import ProviderConnection


class ProviderConnectionRepository(BaseRepository[ProviderConnection]):
    """Data access for provider credential storage."""

    model = ProviderConnection

    async def get_by_id_and_user(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[ProviderConnection]:
        result = await db.execute(
            select(ProviderConnection).where(
                ProviderConnection.id == connection_id,
                ProviderConnection.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_product(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        provider: str,
        product: str,
    ) -> Optional[ProviderConnection]:
        result = await db.execute(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id,
                ProviderConnection.provider == provider,
                ProviderConnection.product == product,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
    ) -> list[ProviderConnection]:
        result = await db.execute(
            select(ProviderConnection)
            .where(ProviderConnection.user_id == user_id)
            .order_by(ProviderConnection.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete(
        self,
        db: AsyncSession,
        connection: ProviderConnection,
    ) -> None:
        await db.delete(connection)
        await db.flush()
