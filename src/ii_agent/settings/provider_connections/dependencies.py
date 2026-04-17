"""FastAPI dependencies for provider connection settings."""

from typing import Annotated

from fastapi import Depends

from ii_agent.core.dependencies import ContainerDep
from ii_agent.settings.provider_connections.service import ProviderConnectionService


def _get_provider_connection_service(container: ContainerDep) -> ProviderConnectionService:
    return container.provider_connection_service


ProviderConnectionServiceDep = Annotated[
    ProviderConnectionService,
    Depends(_get_provider_connection_service),
]
