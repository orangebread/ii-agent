"""Typed execution binding and pause checkpoint persistence."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.runtime_capabilities import RuntimeProfile
from ii_agent.tasks.schemas import (
    CodexResumeCheckpoint,
    RunExecutionBinding,
    StandardAgentResumeCheckpoint,
)
from ii_agent.tasks.service import RunTaskService


logger = logging.getLogger(__name__)


class RunCheckpointService:
    """Owns typed run execution bindings and resume checkpoints."""

    def __init__(self, *, run_task_service: RunTaskService) -> None:
        self._run_task_service = run_task_service

    async def write_execution_binding(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        binding: RunExecutionBinding,
    ) -> None:
        await self._run_task_service.update_task_data(
            db,
            task_id=task_id,
            updates={"execution_binding": binding.model_dump(mode="json", exclude_none=True)},
        )

    async def write_standard_resume_checkpoint(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        session_id: uuid.UUID,
        pending_tool_ids: list[str],
        pause_reason: str,
    ) -> None:
        checkpoint = StandardAgentResumeCheckpoint(
            run_id=str(task_id),
            paused_output_ref={
                "run_id": str(task_id),
                "session_id": str(session_id),
            },
            pending_tool_ids=pending_tool_ids,
            pause_reason=pause_reason,
        )
        await self._run_task_service.update_task_data(
            db,
            task_id=task_id,
            updates={"resume_checkpoint": checkpoint.model_dump(mode="json", exclude_none=True)},
        )

    async def write_codex_resume_checkpoint(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        checkpoint: CodexResumeCheckpoint,
    ) -> None:
        await self._run_task_service.update_task_data(
            db,
            task_id=task_id,
            updates={"resume_checkpoint": checkpoint.model_dump(mode="json", exclude_none=True)},
        )

    async def clear_resume_checkpoint(self, db: AsyncSession, *, task_id: uuid.UUID) -> None:
        await self._run_task_service.update_task_data(
            db,
            task_id=task_id,
            updates={"resume_checkpoint": None},
        )

    @staticmethod
    def load_execution_binding(data: dict[str, Any] | None) -> RunExecutionBinding | None:
        if not isinstance(data, dict):
            return None
        raw = data.get("execution_binding")
        if not isinstance(raw, dict):
            return None
        try:
            return RunExecutionBinding.model_validate(raw)
        except ValidationError:
            logger.warning("Ignoring invalid run execution binding payload", exc_info=True)
            return None

    @staticmethod
    def load_runtime_profile(data: dict[str, Any] | None) -> RuntimeProfile | None:
        binding = RunCheckpointService.load_execution_binding(data)
        return binding.runtime_profile if binding is not None else None

    @staticmethod
    def load_resume_checkpoint(
        data: dict[str, Any] | None,
    ) -> StandardAgentResumeCheckpoint | CodexResumeCheckpoint | None:
        if not isinstance(data, dict):
            return None
        raw = data.get("resume_checkpoint")
        if not isinstance(raw, dict):
            return None
        kind = raw.get("kind")
        try:
            if kind == "standard_agent":
                return StandardAgentResumeCheckpoint.model_validate(raw)
            if kind == "codex_app_server":
                return CodexResumeCheckpoint.model_validate(raw)
        except ValidationError:
            logger.warning("Ignoring invalid run resume checkpoint payload", exc_info=True)
            return None
        return None
