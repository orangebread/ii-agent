from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ii_agent.agents.tools.dev.add_user_env import AddUserEnvTool
from ii_agent.agents.tools.dev.ask_user_env import AskUserEnvTool


@asynccontextmanager
async def _db_cm():
    yield object()


@pytest.mark.asyncio
async def test_ask_user_env_persists_and_syncs_secrets_via_orchestrator():
    tool = AskUserEnvTool()
    tool._agent = SimpleNamespace(session_id=uuid4(), user_id=uuid4())

    container = SimpleNamespace(
        config=MagicMock(),
        sandbox_service=MagicMock(),
        project_service=SimpleNamespace(
            get_session_project_or_none=AsyncMock(
                return_value=SimpleNamespace(project_path="/workspace/project")
            )
        ),
    )
    orchestrator = MagicMock()
    orchestrator.add_secrets = AsyncMock(
        return_value=SimpleNamespace(
            project_path_used="/workspace/custom",
            restart_required=True,
        )
    )

    with (
        patch("ii_agent.agents.tools.dev.ask_user_env.get_app_container", return_value=container),
        patch("ii_agent.agents.tools.dev.ask_user_env.get_db_session_local", new=lambda: _db_cm()),
        patch(
            "ii_agent.agents.tools.dev.ask_user_env.ProjectSecretOrchestrator",
            return_value=orchestrator,
        ),
    ):
        result = await tool.execute(
            {
                "project_directory": "/workspace/custom",
                "requested_keys": [{"key": "OPENAI_API_KEY"}],
                "OPENAI_API_KEY": "sk-test",
            }
        )

    container.project_service.get_session_project_or_none.assert_awaited_once()
    orchestrator.add_secrets.assert_awaited_once()
    call = orchestrator.add_secrets.await_args
    assert call.kwargs["secrets"] == {"OPENAI_API_KEY": "sk-test"}
    assert call.kwargs["project_path"] == "/workspace/custom"
    assert call.kwargs["sync_policy"] == "ensure"
    assert result.is_error is False
    assert result.user_display_content == {
        "project_directory": "/workspace/custom",
        "keys": ["OPENAI_API_KEY"],
        "message": None,
        "restart_required": True,
    }
    assert "need to be restarted" in result.llm_content


@pytest.mark.asyncio
async def test_add_user_env_reports_runtime_sync_from_orchestrator():
    tool = AddUserEnvTool()
    tool._agent = SimpleNamespace(session_id=uuid4(), user_id=uuid4())

    container = SimpleNamespace(
        config=MagicMock(),
        sandbox_service=MagicMock(),
    )
    orchestrator = MagicMock()
    orchestrator.add_secrets = AsyncMock(
        return_value=SimpleNamespace(
            project_path_used="/workspace/project",
            runtime_synced=True,
            restart_required=True,
        )
    )

    with (
        patch("ii_agent.agents.tools.dev.add_user_env.get_app_container", return_value=container),
        patch("ii_agent.agents.tools.dev.add_user_env.get_db_session_local", new=lambda: _db_cm()),
        patch(
            "ii_agent.agents.tools.dev.add_user_env.ProjectSecretOrchestrator",
            return_value=orchestrator,
        ),
    ):
        result = await tool.execute(
            {
                "project_directory": "/workspace/project",
                "secrets": [
                    {"key": "OPENAI_API_KEY", "value": "sk-test"},
                    {"key": "ANTHROPIC_API_KEY", "value": "ak-test"},
                ],
            }
        )

    orchestrator.add_secrets.assert_awaited_once()
    call = orchestrator.add_secrets.await_args
    assert call.kwargs["secrets"] == {
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "ak-test",
    }
    assert call.kwargs["project_path"] == "/workspace/project"
    assert call.kwargs["sync_policy"] == "ensure"
    assert result.is_error is False
    assert result.user_display_content == {
        "project_directory": "/workspace/project",
        "secrets": {
            "OPENAI_API_KEY": "***",
            "ANTHROPIC_API_KEY": "***",
        },
        "keys": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "synced_to_sandbox": True,
        "restart_required": True,
    }
    assert "need to be restarted" in result.llm_content
