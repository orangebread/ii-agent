"""FastAPI dependencies for projects domain.

Thin accessors that pull services from :class:`ApplicationContainer`
or instantiate per-request repositories/services that are not yet
container-managed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from ii_agent.core.config.settings import get_settings
from ii_agent.core.dependencies import ContainerDep
from ii_agent.projects.repository import ProjectRepository
from ii_agent.projects.service import ProjectService
from ii_agent.projects.deployment_orchestration_service import DeploymentOrchestrationService
from ii_agent.projects.databases.service import DatabaseService
from ii_agent.projects.secrets.orchestrator import ProjectSecretOrchestrator
from ii_agent.projects.secrets.service import SecretService
from ii_agent.projects.secrets.env_sync_service import SandboxEnvSyncService


# ==================== Repository Dependencies ====================


def get_project_repository() -> ProjectRepository:
    """Provide ProjectRepository instance."""
    return ProjectRepository()


ProjectRepositoryDep = Annotated[ProjectRepository, Depends(get_project_repository)]


# ==================== Service Dependencies (container-backed) =============


def _get_project_service(container: ContainerDep) -> ProjectService:
    return container.project_service


ProjectServiceDep = Annotated[ProjectService, Depends(_get_project_service)]


def _get_deployment_orchestration_service(
    container: ContainerDep,
) -> DeploymentOrchestrationService:
    return container.deployment_orchestration_service


DeploymentOrchestrationServiceDep = Annotated[
    DeploymentOrchestrationService, Depends(_get_deployment_orchestration_service)
]


# ==================== Domain-specific services (factory) ==================
# These are not yet container-managed; instantiated per request.


def get_secret_service(
    project_repo: ProjectRepositoryDep,
) -> SecretService:
    """Provide SecretService instance."""
    return SecretService(project_repo=project_repo, config=get_settings())


SecretServiceDep = Annotated[SecretService, Depends(get_secret_service)]


def get_database_service(
    project_repo: ProjectRepositoryDep,
) -> DatabaseService:
    """Provide DatabaseService instance."""
    return DatabaseService(project_repo=project_repo, config=get_settings())


DatabaseServiceDep = Annotated[DatabaseService, Depends(get_database_service)]


# ── Sandbox env sync ──────────────────────────────────────────────────────


def _get_sandbox_env_sync_service(container: ContainerDep) -> SandboxEnvSyncService:
    return SandboxEnvSyncService(sandbox_service=container.sandbox_service)


SandboxEnvSyncServiceDep = Annotated[SandboxEnvSyncService, Depends(_get_sandbox_env_sync_service)]


def get_project_secret_orchestrator(
    secret_service: SecretServiceDep,
    database_service: DatabaseServiceDep,
    sandbox_env_sync: SandboxEnvSyncServiceDep,
) -> ProjectSecretOrchestrator:
    """Provide the canonical project-secret orchestration service."""
    return ProjectSecretOrchestrator(
        secret_service=secret_service,
        database_service=database_service,
        env_sync_service=sandbox_env_sync,
    )


ProjectSecretOrchestratorDep = Annotated[
    ProjectSecretOrchestrator, Depends(get_project_secret_orchestrator)
]


__all__ = [
    # Repository
    "get_project_repository",
    "ProjectRepositoryDep",
    # Container-backed services
    "ProjectServiceDep",
    "DeploymentOrchestrationServiceDep",
    # Factory services
    "SecretServiceDep",
    "DatabaseServiceDep",
    "SandboxEnvSyncServiceDep",
    "ProjectSecretOrchestratorDep",
]
