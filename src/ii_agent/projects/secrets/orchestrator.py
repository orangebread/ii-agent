"""Canonical orchestration for project-secret persistence and runtime sync."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.projects.databases.service import DatabaseService
from ii_agent.projects.secrets.env_sync_service import SandboxEnvSyncService
from ii_agent.projects.secrets.service import SecretService
from ii_agent.projects.secrets.utils import _decrypt_secrets_payload

if TYPE_CHECKING:
    from ii_agent.projects.models import Project


SecretSyncPolicy = Literal["none", "existing", "ensure"]


@dataclass
class SecretMutationResult:
    """Result of a project-secret mutation."""

    project: "Project"
    secrets: dict[str, Any]
    database_url: str | None
    runtime_synced: bool
    restart_required: bool
    project_path_used: str | None


class ProjectSecretOrchestrator:
    """Own secret persistence plus optional runtime env materialization."""

    def __init__(
        self,
        *,
        secret_service: SecretService,
        database_service: DatabaseService,
        env_sync_service: SandboxEnvSyncService,
    ) -> None:
        self._secret_service = secret_service
        self._database_service = database_service
        self._env_sync_service = env_sync_service

    async def add_secrets(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        secrets: dict[str, Any],
        sync_policy: SecretSyncPolicy = "none",
        project_path: str | None = None,
    ) -> SecretMutationResult:
        database_url = secrets.get("DATABASE_URL")
        if isinstance(database_url, str) and database_url:
            await self._database_service.upsert_database_from_url(
                db,
                session_id=session_id,
                connection_string=database_url,
            )

        project = await self._secret_service.add_secrets(
            db,
            session_id=session_id,
            user_id=user_id,
            secrets=secrets,
        )
        return await self._finalize_mutation(
            db,
            session_id=session_id,
            user_id=user_id,
            project=project,
            sync_policy=sync_policy,
            project_path=project_path,
        )

    async def replace_secrets(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        secrets: dict[str, Any],
        sync_policy: SecretSyncPolicy = "none",
        project_path: str | None = None,
    ) -> SecretMutationResult:
        database_url = secrets.get("DATABASE_URL")
        if isinstance(database_url, str) and database_url:
            await self._database_service.upsert_database_from_url(
                db,
                session_id=session_id,
                connection_string=database_url,
            )

        project = await self._secret_service.replace_session_project_secrets(
            db,
            session_id=session_id,
            user_id=user_id,
            secrets=secrets,
        )
        return await self._finalize_mutation(
            db,
            session_id=session_id,
            user_id=user_id,
            project=project,
            sync_policy=sync_policy,
            project_path=project_path,
        )

    async def delete_secrets(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        secret_keys: list[str],
        sync_policy: SecretSyncPolicy = "none",
        project_path: str | None = None,
    ) -> SecretMutationResult:
        project = await self._secret_service.delete_secrets(
            db,
            session_id=session_id,
            user_id=user_id,
            secret_keys=secret_keys,
        )
        return await self._finalize_mutation(
            db,
            session_id=session_id,
            user_id=user_id,
            project=project,
            sync_policy=sync_policy,
            project_path=project_path,
        )

    async def _finalize_mutation(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        project: "Project",
        sync_policy: SecretSyncPolicy,
        project_path: str | None,
    ) -> SecretMutationResult:
        current_secrets = _decrypt_secrets_payload(project.secrets_json) or {}
        if not isinstance(current_secrets, dict):
            current_secrets = {}

        current_database_url = await self._database_service.get_project_db_connection(
            db,
            project_id=project.id,
            user_id=user_id,
        )
        runtime_synced = False
        restart_required = False
        project_path_used = project_path or project.project_path

        if sync_policy != "none":
            # Persist first so runtime sync always materializes committed state.
            await db.commit()
            sync_result = await self._env_sync_service.sync_env_files(
                db,
                session_id=session_id,
                user_id=user_id,
                secrets=current_secrets,
                project_path=project_path_used,
                database_url=current_database_url,
                provision_if_missing=sync_policy == "ensure",
            )
            runtime_synced = sync_result.runtime_synced
            restart_required = sync_result.restart_required

        return SecretMutationResult(
            project=project,
            secrets=current_secrets,
            database_url=current_database_url,
            runtime_synced=runtime_synced,
            restart_required=restart_required,
            project_path_used=project_path_used,
        )
