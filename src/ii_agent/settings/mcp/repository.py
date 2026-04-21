"""Repository layer for mcp_settings domain - data access only."""

import uuid
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.db.base import BaseRepository
from ii_agent.settings.mcp.models import MCPSetting


class MCPSettingRepository(BaseRepository[MCPSetting]):
    """Data access layer for MCPSetting model."""

    model = MCPSetting

    async def get_by_id_and_user(
        self, db: AsyncSession, setting_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[MCPSetting]:
        """Get an MCP setting by ID for a specific user."""
        result = await db.execute(
            select(MCPSetting).where(
                MCPSetting.id == setting_id,
                MCPSetting.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_tool_type(
        self, db: AsyncSession, user_id: uuid.UUID, tool_type: str
    ) -> Optional[MCPSetting]:
        """Get an MCP setting by user ID and tool_type from JSONB metadata."""
        result = await db.execute(
            select(MCPSetting).where(
                MCPSetting.user_id == user_id,
                MCPSetting.mcp_metadata["tool_type"].astext == tool_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_runtime_settings_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | str,
        *,
        only_active: bool = False,
    ) -> List[MCPSetting]:
        """List provider-backed runtime settings for a user."""
        query = select(MCPSetting).where(
            MCPSetting.user_id == user_id,
            MCPSetting.mcp_metadata["tool_type"].astext.in_(("codex", "claude_code")),
        )
        if only_active:
            query = query.where(MCPSetting.is_active)
        query = query.order_by(MCPSetting.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def has_provider_connection_reference(
        self,
        db: AsyncSession,
        provider_connection_id: uuid.UUID | str,
    ) -> bool:
        result = await db.execute(
            select(MCPSetting.id)
            .where(MCPSetting.provider_connection_id == provider_connection_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        no_metadata: bool = False,
    ) -> List[MCPSetting]:
        """List all MCP settings for a user."""
        query = select(MCPSetting).where(MCPSetting.user_id == user_id)

        if only_active:
            query = query.where(MCPSetting.is_active)

        if no_metadata:
            query = query.where(
                or_(
                    MCPSetting.mcp_metadata.is_(None),
                    MCPSetting.mcp_metadata == {},
                )
            )

        query = query.order_by(MCPSetting.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def list_active_by_user(self, db: AsyncSession, user_id: uuid.UUID) -> List[MCPSetting]:
        """List all active MCP settings for a user."""
        return await self.list_by_user(db, user_id, only_active=True)

    async def delete(self, db: AsyncSession, setting: MCPSetting) -> None:
        """Delete an MCP setting."""
        await db.delete(setting)
        await db.flush()
