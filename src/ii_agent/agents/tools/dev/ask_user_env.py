from typing import TYPE_CHECKING, Any

from ii_agent.agents.tools.base import BaseAgentTool, ToolResult
from ii_agent.core.container import get_app_container
from ii_agent.core.db import get_db_session_local
from ii_agent.core.logger import logger
from ii_agent.projects.exceptions import ProjectNotFoundError
from ii_agent.projects.repository import ProjectRepository
from ii_agent.projects.databases.service import DatabaseService
from ii_agent.projects.secrets.env_sync_service import SandboxEnvSyncService
from ii_agent.projects.secrets.orchestrator import ProjectSecretOrchestrator
from ii_agent.projects.secrets.service import SecretService

if TYPE_CHECKING:
    from ii_agent.agents.agent import IIAgent
    from ii_agent.agents.tools.function import FunctionCall

NAME = "ask_user_env"
DISPLAY_NAME = "Ask User for Environment Variables"
DESCRIPTION = """Requests environment variables or secrets from the user via a UI prompt.

Usage:
- Call this tool when the project needs API keys, tokens, or other secrets that the user must provide.
- The agent loop pauses before execution and the frontend shows a secrets input form.
- When the user confirms, the backend persists the provided secrets, syncs runtime env files,
  and then continues the run.

Each requested key should include:
- `key`: The environment variable name (e.g., OPENAI_API_KEY)
- `description`: A helpful description explaining what this key is used for
"""
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_directory": {
            "type": "string",
            "description": "Absolute or workspace-relative path to the project root.",
        },
        "requested_keys": {
            "type": "array",
            "description": "List of environment variable keys to request from the user.",
            "items": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Environment variable name (e.g., OPENAI_API_KEY).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of what this key is used for.",
                    },
                },
                "required": ["key"],
            },
        },
        "message": {
            "type": "string",
            "description": "Optional message to display to the user explaining why these secrets are needed.",
        },
    },
    "required": ["project_directory", "requested_keys"],
}


class AskUserEnvTool(BaseAgentTool):
    name = NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    input_schema = INPUT_SCHEMA
    read_only = True
    requires_confirmation = True
    requires_sandbox = False

    def __init__(self) -> None:
        self._agent: "IIAgent | None" = None

    async def on_tool_start(self, agent: "IIAgent", fc: "FunctionCall") -> None:
        self._agent = agent

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        project_dir = tool_input.get("project_directory", "")
        requested_keys = tool_input.get("requested_keys", [])
        message = tool_input.get("message")

        keys_list = [
            item.get("key")
            for item in requested_keys
            if isinstance(item, dict) and isinstance(item.get("key"), str) and item.get("key")
        ]
        secrets = {
            key: str(tool_input[key])
            for key in keys_list
            if key in tool_input and tool_input[key] is not None and str(tool_input[key])
        }

        session_id = getattr(self._agent, "session_id", None)
        user_id = getattr(self._agent, "user_id", None)

        if not session_id:
            return ToolResult(
                llm_content="No active session found for ask_user_env.",
                user_display_content="No active session found.",
                is_error=True,
            )
        if not secrets:
            return ToolResult(
                llm_content="No environment variable values were provided for ask_user_env.",
                user_display_content="No environment variable values were provided.",
                is_error=True,
            )

        try:
            import uuid as _uuid

            container = get_app_container()

            if not user_id:
                async with get_db_session_local() as db:
                    session_uuid = _uuid.UUID(str(session_id))
                    session_obj = await container.session_service.get_session_by_id(
                        db, session_uuid
                    )
                    if session_obj:
                        user_id = str(session_obj.user_id)
            if not user_id:
                return ToolResult(
                    llm_content="Project owner could not be resolved for this session.",
                    user_display_content="Session user not found.",
                    is_error=True,
                )

            session_uuid = _uuid.UUID(str(session_id))
            user_uuid = _uuid.UUID(str(user_id))
            secret_orchestrator = ProjectSecretOrchestrator(
                secret_service=SecretService(
                    project_repo=ProjectRepository(),
                    config=container.config,
                ),
                database_service=DatabaseService(
                    project_repo=ProjectRepository(),
                    config=container.config,
                ),
                env_sync_service=SandboxEnvSyncService(
                    sandbox_service=container.sandbox_service,
                ),
            )

            async with get_db_session_local() as db:
                project = await container.project_service.get_session_project_or_none(
                    db,
                    session_id=session_uuid,
                    user_id=user_uuid,
                )
                if not project:
                    raise ProjectNotFoundError(session_id=str(session_id))
                result = await secret_orchestrator.add_secrets(
                    db,
                    session_id=session_uuid,
                    user_id=user_uuid,
                    secrets=secrets,
                    project_path=project_dir or project.project_path,
                    sync_policy="ensure",
                )
        except ProjectNotFoundError:
            return ToolResult(
                llm_content=(
                    "Project is not initialized; initialize a project before asking for "
                    "environment variables."
                ),
                user_display_content="Project is not initialized",
                is_error=True,
            )
        except Exception as exc:
            logger.warning(
                f"AskUserEnvTool: Failed to resolve project for session {session_id}: {exc}"
            )
            return ToolResult(
                llm_content=f"Failed to verify project before saving env vars: {exc}",
                user_display_content=f"Failed to verify project before saving env vars: {exc}",
                is_error=True,
            )

        project_path = result.project_path_used
        key_list_display = (
            ", ".join(sorted(secrets)) if secrets else "requested environment variables"
        )
        restart_note = ""
        if result.restart_required:
            restart_note = (
                " Existing terminals or development servers started before this change may "
                "need to be restarted to pick up the new environment."
            )

        return ToolResult(
            llm_content=(
                f"Environment variables were saved for `{project_path}`. "
                f"Saved keys: {key_list_display}.{restart_note}"
            ),
            user_display_content={
                "project_directory": project_path,
                "keys": sorted(secrets),
                "message": message,
                "restart_required": result.restart_required,
            },
            is_error=False,
        )
