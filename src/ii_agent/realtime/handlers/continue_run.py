"""Handler for continue_run command (Human-in-the-Loop).

Extracted from ``server.socket.command.continue_run_handler``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ii_agent.agents.factory.agent import agent_factory
from ii_agent.agents.models.response import ToolExecution
from ii_agent.agents.sessions import AgentSessionStore
from ii_agent.agents.types import AgentType
from ii_agent.core.container import ApplicationContainer
from ii_agent.core.db import get_db_session_local, get_session_factory
from ii_agent.core.logger import logger
from ii_agent.realtime.events.app_events import (
    AgentContinueEvent,
    AgentProcessingEvent,
    ErrorCode,
)
from ii_agent.realtime.handlers.base import BaseCommandHandler, CommandType
from ii_agent.realtime.pubsub import AsyncIOPubSub
from ii_agent.realtime.schemas import ContinueRunContent
from ii_agent.sessions.schemas import SessionInfo
from ii_agent.tasks.schemas import CodexResumeCheckpoint, StandardAgentResumeCheckpoint


class ContinueRunHandler(BaseCommandHandler[ContinueRunContent]):
    """Handler for continue_run command (Human-in-the-Loop)."""

    _content_type = ContinueRunContent

    def __init__(self, pubsub: AsyncIOPubSub, container: ApplicationContainer) -> None:
        super().__init__(pubsub=pubsub, container=container)

    def get_command_type(self) -> CommandType:
        return CommandType.CONTINUE_RUN

    @staticmethod
    def _apply_user_input_to_tool(
        tool: ToolExecution, user_input: dict[str, str], run_id: str
    ) -> None:
        """Persist user-provided values onto the paused tool execution."""
        if tool.user_input_schema:
            for field in tool.user_input_schema:
                if field.name in user_input:
                    field.value = user_input[field.name]
                    logger.info(
                        "User provided input for field '%s' in run %s",
                        field.name,
                        run_id,
                    )

        if tool.tool_args is None:
            tool.tool_args = {}
        tool.tool_args.update(user_input)

    @staticmethod
    def _extract_run_context(
        run_task_data: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Recover the original query-time agent config from RunTask metadata."""
        if not isinstance(run_task_data, dict):
            return None, None

        tool_args = run_task_data.get("tool_args")
        metadata = run_task_data.get("metadata")

        normalized_tool_args = tool_args if isinstance(tool_args, dict) else None
        normalized_metadata = metadata if isinstance(metadata, dict) else None
        return normalized_tool_args, normalized_metadata

    async def handle(self, content: ContinueRunContent, session_info: SessionInfo) -> None:
        """Handle the continue_run command."""
        # Only work for v1 API version
        if session_info.api_version != "v1":
            await self._send_error_event(
                session_info.id,
                error_code=ErrorCode.UNSUPPORTED_API_VERSION,
            )
            return

        # Extract required fields
        run_id = content.run_id
        confirmed = content.is_confirmation_positive
        decision = content.resolved_decision
        user_input = content.user_input

        # Send AGENT_CONTINUE event immediately to stop waiting for input
        await self.send_event(
            AgentContinueEvent(
                session_id=UUID(str(session_info.id)),
                content={
                    "message": "Agent continuing...",
                    "confirmed": confirmed,
                    "decision": decision,
                    "run_id": run_id,
                },
            )
        )

        try:
            async with get_db_session_local() as db:
                run_task = await self._container.run_task_service.get_task_by_id(
                    db,
                    task_id=UUID(run_id),
                )
                run_task_data = getattr(run_task, "data", None)
                checkpoint_service = self._container.run_checkpoint_service
                execution_binding = checkpoint_service.load_execution_binding(run_task_data)
                resume_checkpoint = checkpoint_service.load_resume_checkpoint(run_task_data)

                model_setting_id = (
                    execution_binding.model_setting_id
                    if execution_binding is not None
                    else session_info.model_setting_id
                )
                if not model_setting_id:
                    if not isinstance(resume_checkpoint, CodexResumeCheckpoint):
                        session_store = AgentSessionStore(session_maker=get_session_factory())
                        run_response = await session_store.get_by_run_id(
                            run_id=run_id, session_id=str(session_info.id)
                        )
                        if not run_response:
                            await self._send_error_event(
                                session_info.id,
                                error_code=ErrorCode.RUN_NOT_FOUND,
                                message=f"Run {run_id} not found",
                            )
                            return
                    raise ValueError("Run has no stored model_setting_id for continue_run")

                llm_config = (
                    await self._container.model_setting_service.resolve_config_by_setting_id(
                        db,
                        setting_id=model_setting_id,
                        user_id=session_info.user_id,
                    )
                )

            is_codex_runtime = (
                isinstance(resume_checkpoint, CodexResumeCheckpoint)
                or getattr(llm_config, "runtime_product", None) == "codex"
            )

            if is_codex_runtime:
                if not isinstance(resume_checkpoint, CodexResumeCheckpoint):
                    raise ValueError("Codex run is missing a persisted resume checkpoint")

                tool_args, metadata = self._extract_run_context(run_task_data)

                agent = await agent_factory.create_agent(
                    user_id=str(session_info.user_id),
                    session_id=str(session_info.id),
                    llm_config=llm_config,
                    agent_type=AgentType(session_info.agent_type)
                    if session_info.agent_type
                    else AgentType.GENERAL,
                    tool_args=tool_args,
                    metadata=metadata,
                    skill_creator=self._create_skill_creator(session_info.user_id),
                )

                await self.send_event(
                    AgentProcessingEvent(
                        session_id=UUID(str(session_info.id)),
                        message="Resuming agent execution...",
                        content={
                            "message": "Resuming agent execution...",
                            "run_id": run_id,
                        },
                    )
                )

                event_stream = agent.acontinue_run(
                    run_id=run_id,
                    stream=True,
                    decision=decision,
                    user_input=user_input,
                    policy_patch=content.policy_patch,
                    resume_checkpoint=resume_checkpoint,
                )

                await self.process_agent_event_stream(
                    event_stream,
                    session_info,
                    run_id=UUID(run_id),
                    is_user_key=llm_config.is_user_model(),
                    llm_config=llm_config,
                )
                return

            session_store = AgentSessionStore(session_maker=get_session_factory())
            paused_run_id = run_id
            paused_session_id = str(session_info.id)
            if isinstance(resume_checkpoint, StandardAgentResumeCheckpoint):
                paused_run_id = resume_checkpoint.paused_output_ref.run_id
                paused_session_id = resume_checkpoint.paused_output_ref.session_id

            run_response = await session_store.get_by_run_id(
                run_id=paused_run_id, session_id=paused_session_id
            )

            if not run_response:
                await self._send_error_event(
                    session_info.id,
                    error_code=ErrorCode.RUN_NOT_FOUND,
                    message=f"Run {run_id} not found",
                )
                return

            # Handle tools requiring confirmation
            for _t in run_response.tools_requiring_confirmation:
                if confirmed:
                    _t.confirmed = True
                    if user_input:
                        self._apply_user_input_to_tool(_t, user_input, run_id)
                    logger.info(f"User confirmed requirement for run {run_id}")
                else:
                    _t.confirmed = False
                    logger.info(f"User rejected requirement for run {run_id}")

            # Handle tools requiring user input
            for _t in run_response.tools_requiring_user_input:
                if confirmed and user_input:
                    self._apply_user_input_to_tool(_t, user_input, run_id)
                    _t.answered = True
                else:
                    _t.answered = False
                    logger.info(f"User did not provide input for run {run_id}")

            tool_args, metadata = self._extract_run_context(run_task_data)

            # Create agent with same configuration (matches query handler pattern)
            agent = await agent_factory.create_agent(
                user_id=str(session_info.user_id),
                session_id=str(session_info.id),
                llm_config=llm_config,
                agent_type=AgentType(session_info.agent_type)
                if session_info.agent_type
                else AgentType.GENERAL,
                session_store=session_store,
                tool_args=tool_args,
                metadata=metadata,
                skill_creator=self._create_skill_creator(session_info.user_id),
            )

            # Send processing event
            await self.send_event(
                AgentProcessingEvent(
                    session_id=UUID(str(session_info.id)),
                    message="Resuming agent execution...",
                    content={
                        "message": "Resuming agent execution...",
                        "run_id": run_id,
                    },
                )
            )

            # Continue the run with updated requirements
            event_stream = agent.acontinue_run(
                run_id=run_response.run_id,
                updated_tools=run_response.tools,
                stream=True,
                stream_events=True,
            )

            await self.process_agent_event_stream(
                event_stream,
                session_info,
                run_id=UUID(run_response.run_id),
                is_user_key=llm_config.is_user_model(),
                llm_config=llm_config,
            )

        except ValueError as e:
            logger.error(f"ValueError in continue_run: {str(e)}")
            await self._send_error_event(
                session_info.id,
                error_code=ErrorCode.VALIDATION_ERROR,
                message=str(e),
            )
        except Exception as e:
            logger.error(f"Error in continue_run handler: {str(e)}", exc_info=True)
            await self._send_error_event(
                session_info.id,
                error_code=ErrorCode.EXECUTION_ERROR,
                message=f"Failed to continue run: {str(e)}",
            )
