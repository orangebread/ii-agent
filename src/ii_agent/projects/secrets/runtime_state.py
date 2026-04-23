"""Read-only runtime state for project-backed secret materialization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.logger import logger
from ii_agent.projects.databases.service import DatabaseService
from ii_agent.projects.repository import ProjectRepository
from ii_agent.projects.secrets.utils import _decrypt_secrets_payload, sanitize_secret_payload


@dataclass(frozen=True)
class ProjectSecretRuntimeState:
    """Normalized project-backed secret state used to reconcile sandboxes."""

    project_id: uuid.UUID
    project_path: str | None
    secrets: dict[str, Any]
    database_url: str | None


class ProjectSecretRuntimeStateService:
    """Resolve the committed runtime secret view for a session project."""

    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        database_service: DatabaseService,
    ) -> None:
        self._project_repo = project_repo
        self._database_service = database_service

    async def get_runtime_state(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProjectSecretRuntimeState | None:
        """Return the current committed project secret state for a session."""
        project = await self._project_repo.get_by_session_and_user(
            db,
            session_id=session_id,
            user_id=user_id,
        )
        if project is None:
            return None

        secrets, invalid_keys = sanitize_secret_payload(
            _decrypt_secrets_payload(project.secrets_json)
        )
        if invalid_keys:
            logger.warning(
                "Ignoring invalid persisted secret key(s) during sandbox reconcile: %s",
                ", ".join(sorted(invalid_keys)),
            )

        database_url = await self._database_service.get_project_db_connection(
            db,
            project_id=project.id,
            user_id=user_id,
        )

        return ProjectSecretRuntimeState(
            project_id=project.id,
            project_path=project.project_path,
            secrets=secrets,
            database_url=database_url,
        )
