"""Service layer for projects domain - business logic only."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.config.settings import Settings
from ii_agent.core.logger import logger

from ii_agent.projects.exceptions import ProjectNotFoundError
from ii_agent.projects.models import Project
from ii_agent.projects.repository import ProjectRepository
from ii_agent.sessions.repository import SessionRepository


class ProjectService:
    """Service for managing projects - business logic layer."""

    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        session_repo: SessionRepository,
        config: Settings,
    ) -> None:
        self._config = config
        self._project_repo = project_repo
        self._session_repo = session_repo

    async def create_project(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        project_name: str,
        framework: Optional[str] = None,
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        database: Optional[Dict[str, Any]] = None,
    ) -> Optional[Project]:
        """Create or update a project for a session."""
        session = await self._session_repo.get_by_id(db, session_id)
        if not session:
            logger.warning(
                "Unable to persist project metadata because session {} was not found", session_id
            )
            return None

        # Check if a project already exists for this session (unique constraint on session_id)
        existing = await self._project_repo.get_by_session_id(db, session_id)
        if existing:
            existing.name = project_name
            if description is not None:
                existing.description = description
            if framework is not None:
                existing.framework = framework
            if project_path is not None:
                existing.project_path = project_path
            if database is not None:
                existing.database_json = database
            await db.flush()
            return existing

        project = Project(
            user_id=session.user_id,
            session_id=session_id,
            name=project_name,
            description=description,
            framework=framework,
            project_path=project_path,
            database_json=database,
        )

        return await self._project_repo.save(db, project)

    async def get_session_project(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Project:
        """Fetch the session project for a user.

        Raises:
            ProjectNotFoundError: If project not found or access denied.
        """
        project = await self._project_repo.get_by_session_and_user(
            db, session_id=session_id, user_id=user_id
        )
        if not project:
            raise ProjectNotFoundError(
                f"Project for session {session_id} not found or access denied"
            )
        return project

    async def get_session_project_or_none(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Project]:
        """Return the most recent project for the given session if the user owns it."""
        return await self._project_repo.get_by_session_and_user(
            db, session_id=session_id, user_id=user_id
        )

    async def get_user_project_by_id(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Project]:
        """Fetch a project by its ID for the provided user."""
        return await self._project_repo.get_by_id_and_user(
            db, project_id=project_id, user_id=user_id
        )

    async def update_session_project_production_url(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        production_url: str,
    ) -> Optional[Project]:
        """Persist the latest deployment URL for the user's session project."""
        project = await self._project_repo.get_by_session_and_user(
            db, session_id=session_id, user_id=user_id
        )
        if not project:
            return None

        project.production_url = production_url
        return await self._project_repo.update(db, project)
