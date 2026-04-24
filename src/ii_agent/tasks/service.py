"""Service layer for run tasks — business logic, returns Pydantic models."""

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.tasks.exceptions import TaskConflictException
from ii_agent.tasks.models import RunTask, TaskLog
from ii_agent.tasks.repository import RunTaskRepository, TaskLogRepository
from ii_agent.tasks.schemas import RunTaskResponse, TaskLogResponse
from ii_agent.tasks.types import RunStatus, TaskType
from ii_agent.core.config.settings import Settings
from ii_agent.core.redis.cache import TypedEntityCache

logger = logging.getLogger(__name__)

KEY_PATTERN = "run_task:{task_id}"


class RunTaskService:
    """Orchestrates run-task business logic.

    - Creates ORM objects internally
    - Delegates persistence to repositories
    - Returns Pydantic response models to callers
    """

    def __init__(
        self,
        *,
        task_repo: RunTaskRepository,
        log_repo: TaskLogRepository,
        cache: TypedEntityCache[RunTaskResponse],
        config: Settings,
    ) -> None:
        self._task_repo = task_repo
        self._log_repo = log_repo
        self._cache = cache
        self._config = config

    # ── Create ─────────────────────────────────────────────────────────────

    async def claim_task(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        task_type: TaskType,
        status: RunStatus = RunStatus.RUNNING,
        data: Dict[str, Any] | None = None,
    ) -> RunTaskResponse:
        """Claim a new run task.
        Raises:
            TaskConflictException: if an active task for (session_id, task_type)
                already exists.
        """
        task = RunTask(
            session_id=session_id,
            task_type=task_type,
            status=status,
            data=data,
        )
        try:
            task = await self._task_repo.save(db, task)
        except IntegrityError:
            await db.rollback()
            raise TaskConflictException(
                task_type=task_type,
                session_id=session_id,
            )

        log = TaskLog(task_id=task.id, status=status)
        await self._log_repo.save(db, log)

        return RunTaskResponse.model_validate(task)

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_task_by_id(
        self, db: AsyncSession, *, task_id: uuid.UUID
    ) -> Optional[RunTaskResponse]:
        _cached_key = KEY_PATTERN.format(task_id=str(task_id))
        cached = await self._cache.get(_cached_key)
        if cached:
            return cached

        task = await self._task_repo.get_by_id(db, task_id)
        if task is None:
            return None

        res = RunTaskResponse.model_validate(task)
        await self._cache.set(_cached_key, res)
        return res

    async def find_active_by_session(
        self, db: AsyncSession, session_id: uuid.UUID
    ) -> Optional[RunTaskResponse]:
        task = await self._task_repo.find_active_by_session(db, session_id)
        if task is None:
            return None
        return RunTaskResponse.model_validate(task)

    async def get_last_by_session_id(
        self, db: AsyncSession, session_id: uuid.UUID
    ) -> Optional[RunTaskResponse]:
        task = await self._task_repo.find_last_by_session(db, session_id)
        if task is None:
            return None
        return RunTaskResponse.model_validate(task)

    async def get_tasks_by_session(
        self, db: AsyncSession, session_id: uuid.UUID
    ) -> list[RunTaskResponse]:
        tasks = await self._task_repo.list_by_session(db, session_id)
        return [RunTaskResponse.model_validate(t) for t in tasks]

    async def get_all_running_session_ids(self, db: AsyncSession) -> list[str]:
        return await self._task_repo.get_running_session_ids(db)

    # ── Update ─────────────────────────────────────────────────────────────

    async def transition_status(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        to_status: RunStatus,
        error_message: str | None = None,
        log_data: Dict[str, Any] | None = None,
    ) -> Optional[RunTaskResponse]:
        """Update status, append audit log, evict cache."""
        task = await self._task_repo.get_by_id(db, task_id)
        if not task:
            return None

        task.status = to_status
        if error_message is not None:
            task.error_message = error_message
        task = await self._task_repo.update(db, task)

        log = TaskLog(task_id=task_id, status=to_status, data=log_data)
        await self._log_repo.save(db, log)

        _cached_key = KEY_PATTERN.format(task_id=str(task_id))
        await self._cache.evict(_cached_key)

        return RunTaskResponse.model_validate(task)

    async def update_task_data(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        updates: Dict[str, Any],
    ) -> Optional[RunTaskResponse]:
        """Merge task metadata updates, preserving existing keys unless cleared."""
        task = await self._task_repo.get_by_id(db, task_id)
        if not task:
            return None

        merged_data: Dict[str, Any] = dict(task.data or {})
        for key, value in updates.items():
            if value is None:
                merged_data.pop(key, None)
            else:
                merged_data[key] = value

        task.data = merged_data or None
        task = await self._task_repo.update(db, task)

        _cached_key = KEY_PATTERN.format(task_id=str(task_id))
        await self._cache.evict(_cached_key)

        return RunTaskResponse.model_validate(task)

    # ── Logs ───────────────────────────────────────────────────────────────

    async def get_logs(self, db: AsyncSession, task_id: uuid.UUID) -> list[TaskLogResponse]:
        logs = await self._log_repo.list_by_task(db, task_id)
        return [TaskLogResponse.model_validate(log) for log in logs]
