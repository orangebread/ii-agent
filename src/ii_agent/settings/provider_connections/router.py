"""Routes for provider connection settings."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from ii_agent.auth.dependencies import CurrentUser, DBSession
from ii_agent.settings.provider_connections.dependencies import ProviderConnectionServiceDep
from ii_agent.settings.provider_connections.schemas import (
    ProviderConnectionInfo,
    ProviderConnectionList,
)

router = APIRouter(prefix="/provider-connections", tags=["Provider Connections"])


@router.get("", response_model=ProviderConnectionList)
async def list_provider_connections(
    current_user: CurrentUser,
    service: ProviderConnectionServiceDep,
    db: DBSession,
) -> ProviderConnectionList:
    """List stored provider credentials for the current user."""
    return await service.list_connections(db, user_id=current_user.id)


@router.get("/{connection_id}", response_model=Optional[ProviderConnectionInfo])
async def get_provider_connection(
    connection_id: str,
    current_user: CurrentUser,
    service: ProviderConnectionServiceDep,
    db: DBSession,
) -> Optional[ProviderConnectionInfo]:
    """Get a single provider connection for the current user."""
    return await service.get_connection(
        db,
        connection_id=connection_id,
        user_id=current_user.id,
    )
