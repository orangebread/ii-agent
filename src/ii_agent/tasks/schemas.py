"""Pydantic schemas for the tasks domain."""

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ii_agent.core.runtime_capabilities import RuntimeProfile
from ii_agent.tasks.types import RunStatus, TaskType


class RunTaskResponse(BaseModel):
    """Public representation of a RunTask."""

    id: UUID
    session_id: UUID
    task_type: TaskType
    status: RunStatus
    error_message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    version: int = Field(default=0)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskLogResponse(BaseModel):
    """Public representation of a TaskLog entry."""

    id: int
    task_id: UUID
    status: RunStatus
    data: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunExecutionBinding(BaseModel):
    """Durable per-run execution identity."""

    version: int = 1
    model_setting_id: UUID
    resolved_model_id: str
    provider: str
    credential_source: str
    provider_connection_id: UUID | None = None
    runtime_product: str | None = None
    mcp_setting_id: UUID | None = None
    runtime_profile: RuntimeProfile


class StandardPausedOutputRef(BaseModel):
    """Reference to paused standard-runtime state in AgentSessionStore."""

    run_id: str
    session_id: str


class StandardAgentResumeCheckpoint(BaseModel):
    """Host-owned reference for paused standard-agent runs."""

    version: int = 1
    kind: Literal["standard_agent"] = "standard_agent"
    run_id: str | None = None
    session_store_backend: Literal["agent_session_store"] = "agent_session_store"
    paused_output_ref: StandardPausedOutputRef
    pending_tool_ids: list[str] = Field(default_factory=list)
    pause_reason: str = "paused"


class CodexResumeCheckpoint(BaseModel):
    """Host-owned reference for paused Codex App Server runs."""

    version: int = 1
    kind: Literal["codex_app_server"] = "codex_app_server"
    thread_id: str
    turn_id: str
    pending_request_id: str
    pending_request_kind: Literal["approval", "user_input"]
    request_payload: dict[str, Any] = Field(default_factory=dict)
    allowed_decisions: list[str] = Field(default_factory=list)
    registered_tool_fingerprint: str | None = None
    pause_reason: str = "paused"
