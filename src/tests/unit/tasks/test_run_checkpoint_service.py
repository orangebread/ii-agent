from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from ii_agent.core.runtime_capabilities import RuntimeCapabilities, RuntimeProfile
from ii_agent.tasks.checkpoint_service import RunCheckpointService
from ii_agent.tasks.schemas import CodexResumeCheckpoint, RunExecutionBinding


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_write_execution_binding_persists_typed_payload():
    run_task_service = AsyncMock()
    service = RunCheckpointService(run_task_service=run_task_service)
    task_id = uuid.uuid4()
    binding = RunExecutionBinding(
        model_setting_id=uuid.uuid4(),
        resolved_model_id="gpt-5.4",
        provider="openai",
        credential_source="provider_oauth",
        provider_connection_id=uuid.uuid4(),
        runtime_product="codex",
        mcp_setting_id=uuid.uuid4(),
        runtime_profile=RuntimeProfile(
            runtime_product="codex",
            provider="openai",
            credential_source="provider_oauth",
            provider_connection_id=uuid.uuid4(),
            mcp_setting_id=uuid.uuid4(),
            capabilities=RuntimeCapabilities(supports_persistent_threads=True),
        ),
    )

    await service.write_execution_binding(AsyncMock(), task_id=task_id, binding=binding)

    run_task_service.update_task_data.assert_awaited_once()
    kwargs = run_task_service.update_task_data.await_args.kwargs
    assert kwargs["task_id"] == task_id
    assert kwargs["updates"]["execution_binding"]["version"] == 1
    assert kwargs["updates"]["execution_binding"]["runtime_profile"]["runtime_product"] == "codex"


def test_load_resume_checkpoint_parses_standard_checkpoint():
    checkpoint = RunCheckpointService.load_resume_checkpoint(
        {
            "resume_checkpoint": {
                "version": 1,
                "kind": "standard_agent",
                "session_store_backend": "agent_session_store",
                "paused_output_ref": {
                    "run_id": "run-123",
                    "session_id": "session-123",
                },
                "pending_tool_ids": ["tool-1"],
                "pause_reason": "approval",
            }
        }
    )

    assert checkpoint is not None
    assert checkpoint.kind == "standard_agent"
    assert checkpoint.paused_output_ref.run_id == "run-123"
    assert checkpoint.pending_tool_ids == ["tool-1"]


@pytest.mark.asyncio
async def test_write_codex_resume_checkpoint_persists_typed_payload():
    run_task_service = AsyncMock()
    service = RunCheckpointService(run_task_service=run_task_service)
    task_id = uuid.uuid4()
    checkpoint = CodexResumeCheckpoint(
        thread_id="thr_123",
        turn_id="turn_123",
        pending_request_id="req_123",
        pending_request_kind="approval",
        request_payload={"method": "item/commandExecution/requestApproval"},
        allowed_decisions=["accept", "decline"],
    )

    await service.write_codex_resume_checkpoint(AsyncMock(), task_id=task_id, checkpoint=checkpoint)

    run_task_service.update_task_data.assert_awaited_once()
    kwargs = run_task_service.update_task_data.await_args.kwargs
    assert kwargs["task_id"] == task_id
    assert kwargs["updates"]["resume_checkpoint"]["kind"] == "codex_app_server"
    assert kwargs["updates"]["resume_checkpoint"]["thread_id"] == "thr_123"


def test_load_resume_checkpoint_parses_codex_checkpoint():
    checkpoint = RunCheckpointService.load_resume_checkpoint(
        {
            "resume_checkpoint": {
                "version": 1,
                "kind": "codex_app_server",
                "thread_id": "thr_123",
                "turn_id": "turn_123",
                "pending_request_id": "req_123",
                "pending_request_kind": "approval",
                "request_payload": {"method": "item/commandExecution/requestApproval"},
                "allowed_decisions": ["accept", "decline"],
                "pause_reason": "approval",
            }
        }
    )

    assert checkpoint is not None
    assert checkpoint.kind == "codex_app_server"
    assert checkpoint.thread_id == "thr_123"
    assert checkpoint.pending_request_kind == "approval"


def test_load_execution_binding_returns_none_for_invalid_payload():
    binding = RunCheckpointService.load_execution_binding(
        {"execution_binding": {"version": 1, "resolved_model_id": "gpt-5.4"}}
    )

    assert binding is None


def test_load_resume_checkpoint_returns_none_for_invalid_payload():
    checkpoint = RunCheckpointService.load_resume_checkpoint(
        {
            "resume_checkpoint": {
                "version": 1,
                "kind": "codex_app_server",
                "thread_id": "thr_123",
            }
        }
    )

    assert checkpoint is None
