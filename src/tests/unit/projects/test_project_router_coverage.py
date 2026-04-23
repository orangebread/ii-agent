"""Targeted coverage tests for project routers and request/response wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as PydanticValidationError

from ii_agent.projects import router as project_router
from ii_agent.projects.databases.router import (
    get_project_database_records,
    get_project_database_schema,
)
from ii_agent.projects.databases.schemas import TableRecordsResult
from ii_agent.projects.deployments.exceptions import DeploymentNotFoundError
from ii_agent.projects.deployments.router import get_project_deployment
from ii_agent.projects.exceptions import ProjectNotFoundError
from ii_agent.projects.secrets.router import (
    delete_session_project_secrets,
    get_session_project_secrets,
    replace_session_project_secrets,
    set_session_project_secrets,
)
from ii_agent.projects.secrets.schemas import (
    ProjectSecretsDeleteRequest,
    ProjectSecretsRequest,
)
from ii_agent.projects.design.router import (
    ai_change,
    ai_iframe_plan,
    get_design_state,
    proxy_design_mode,
    save_design_state,
)
from ii_agent.projects.design.schemas import (
    AIChangeRequest,
    AIChangeResponse,
    DesignStateRequest,
    ElementInfoRequest,
    IframeAIPlanRequest,
    IframeAIPlanResponse,
    StyleChange,
)


USER_ID = "00000000-0000-4000-8000-000000000101"
PROJECT_ID = "00000000-0000-4000-8000-000000000102"
SESSION_ID = "00000000-0000-4000-8000-000000000103"
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000104"


def _user(user_id: str = USER_ID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _project_for_session_response(
    *,
    project_id: str = PROJECT_ID,
    user_id: str = USER_ID,
    session_id: str = SESSION_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        user_id=user_id,
        session_id=session_id,
        name="Demo Project",
        description=None,
        status="ready",
        current_build_status="idle",
        framework=None,
        project_path="/tmp/project",
        production_url=None,
        database_json={"url": "postgres://localhost"},
        storage_json=None,
        secrets_json={"env": "local"},
        current_production_deployment_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_router_get_session_project_forwards_to_service():
    service = AsyncMock()
    service.get_session_project.return_value = _project_for_session_response()
    database_service = AsyncMock()
    database_service.get_session_db_payload.return_value = {"url": "postgres://runtime"}

    result = await project_router.get_session_project(
        SESSION_ID,
        _user(USER_ID),
        service,
        database_service,
        None,
    )

    service.get_session_project.assert_awaited_once_with(
        None,
        session_id=SESSION_ID,
        user_id=USER_ID,
    )
    database_service.get_session_db_payload.assert_awaited_once_with(None, SESSION_ID)
    assert result.id == UUID(PROJECT_ID)


@pytest.mark.asyncio
async def test_databases_router_get_schema_success():
    database_service = AsyncMock()
    database_service.get_project_db_tables.return_value = ["users", "events"]

    result = await get_project_database_schema(
        PROJECT_ID,
        _user(USER_ID),
        database_service,
        None,
    )

    database_service.get_project_db_tables.assert_awaited_once_with(
        None,
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    assert result.project_id == UUID(PROJECT_ID)
    assert result.tables == ["users", "events"]


@pytest.mark.asyncio
async def test_databases_router_get_schema_missing_project():
    database_service = AsyncMock()
    database_service.get_project_db_tables.return_value = None

    with pytest.raises(ProjectNotFoundError):
        await get_project_database_schema(
            PROJECT_ID,
            _user(USER_ID),
            database_service,
            None,
        )


@pytest.mark.asyncio
async def test_databases_router_get_records_success():
    database_service = AsyncMock()
    database_service.get_project_db_records.return_value = TableRecordsResult(
        rows=[{"id": 1}],
        total=1,
    )

    result = await get_project_database_records(
        PROJECT_ID,
        _user(USER_ID),
        database_service,
        None,
        table="users",
        limit=20,
        offset=5,
    )

    database_service.get_project_db_records.assert_awaited_once_with(
        None,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        table_name="users",
        limit=20,
        offset=5,
    )
    assert result.total == 1
    assert result.rows == [{"id": 1}]


@pytest.mark.asyncio
async def test_databases_router_get_records_missing_project():
    database_service = AsyncMock()
    database_service.get_project_db_records.return_value = None

    with pytest.raises(ProjectNotFoundError):
        await get_project_database_records(
            PROJECT_ID,
            _user(USER_ID),
            database_service,
            None,
            table="users",
        )


@pytest.mark.asyncio
async def test_deployments_router_returns_deployment_on_success():
    service = AsyncMock()
    deployment = SimpleNamespace(
        id=DEPLOYMENT_ID,
        project_id=PROJECT_ID,
        provider="aws",
    )
    service.get_project_deployment.return_value = deployment

    result = await get_project_deployment(
        PROJECT_ID,
        _user(USER_ID),
        service,
        None,
    )

    service.get_project_deployment.assert_awaited_once_with(
        None,
        user_id=USER_ID,
        project_id=PROJECT_ID,
    )
    assert result.id == DEPLOYMENT_ID


@pytest.mark.asyncio
async def test_deployments_router_returns_empty_when_not_found():
    service = AsyncMock()
    service.get_project_deployment.side_effect = DeploymentNotFoundError("missing")
    result = await get_project_deployment(PROJECT_ID, _user(USER_ID), service, None)

    assert result.id is None
    assert result.project_id == UUID(PROJECT_ID)


@pytest.mark.asyncio
async def test_secrets_router_get_secrets_maps_project_payload():
    project = _project_for_session_response(session_id="00000000-0000-4000-8000-000000000001")
    service = AsyncMock()
    service.get_session_project.return_value = project

    result = await get_session_project_secrets(
        project.session_id,
        _user(USER_ID),
        service,
        None,
    )

    service.get_session_project.assert_awaited_once_with(
        None,
        session_id=project.session_id,
        user_id=USER_ID,
    )
    assert result.session_id == UUID(project.session_id)
    assert result.secrets == {"env": "local"}


@pytest.mark.asyncio
async def test_secrets_router_set_secrets_delegates_to_orchestrator_and_returns_payload():
    project = _project_for_session_response(session_id="00000000-0000-4000-8000-000000000002")
    secret_orchestrator = AsyncMock()
    secret_orchestrator.add_secrets.return_value = SimpleNamespace(
        project=project,
        secrets={"env": "local"},
        runtime_synced=False,
        restart_required=False,
    )

    payload = ProjectSecretsRequest(secrets={"API_KEY": "abc"})
    result = await set_session_project_secrets(
        project.session_id,
        payload,
        _user(USER_ID),
        secret_orchestrator,
        None,
    )

    secret_orchestrator.add_secrets.assert_awaited_once_with(
        None,
        session_id=project.session_id,
        user_id=USER_ID,
        secrets={"API_KEY": "abc"},
        sync_policy="existing",
    )
    assert result.project_id == UUID(project.id)
    assert result.secrets == {"env": "local"}
    assert result.restart_required is False


@pytest.mark.asyncio
async def test_secrets_router_set_secrets_preserves_database_url_payload():
    project = _project_for_session_response(session_id="00000000-0000-4000-8000-000000000022")
    project.secrets_json = {"DATABASE_URL": "postgres://db.example/app"}
    secret_orchestrator = AsyncMock()
    secret_orchestrator.add_secrets.return_value = SimpleNamespace(
        project=project,
        secrets={"DATABASE_URL": "postgres://canonical-db"},
        runtime_synced=True,
        restart_required=True,
    )

    payload = ProjectSecretsRequest(secrets={"DATABASE_URL": "postgres://db.example/app"})
    result = await set_session_project_secrets(
        project.session_id,
        payload,
        _user(USER_ID),
        secret_orchestrator,
        None,
    )

    secret_orchestrator.add_secrets.assert_awaited_once_with(
        None,
        session_id=project.session_id,
        user_id=USER_ID,
        secrets={"DATABASE_URL": "postgres://db.example/app"},
        sync_policy="existing",
    )
    assert result.project_id == UUID(project.id)
    assert result.secrets == {"DATABASE_URL": "postgres://canonical-db"}
    assert result.restart_required is True


@pytest.mark.asyncio
async def test_secrets_router_replace_secrets_delegates_to_orchestrator():
    project = _project_for_session_response(session_id="00000000-0000-4000-8000-000000000003")
    project.secrets_json = {"API_KEY": "abc", "DATABASE_URL": "postgres://db.example/app"}
    secret_orchestrator = AsyncMock()
    secret_orchestrator.replace_secrets.return_value = SimpleNamespace(
        project=project,
        secrets={"API_KEY": "abc", "DATABASE_URL": "postgres://canonical-db"},
        runtime_synced=True,
        restart_required=False,
    )

    payload = ProjectSecretsRequest(
        secrets={
            "API_KEY": "abc",
            "DATABASE_URL": "postgres://db.example/app",
        }
    )
    result = await replace_session_project_secrets(
        project.session_id,
        payload,
        _user(USER_ID),
        secret_orchestrator,
        None,
    )

    secret_orchestrator.replace_secrets.assert_awaited_once_with(
        None,
        session_id=project.session_id,
        user_id=USER_ID,
        secrets={
            "API_KEY": "abc",
            "DATABASE_URL": "postgres://db.example/app",
        },
        sync_policy="existing",
    )
    assert result.project_id == UUID(project.id)
    assert result.secrets == {"API_KEY": "abc", "DATABASE_URL": "postgres://canonical-db"}
    assert result.restart_required is False


@pytest.mark.asyncio
async def test_secrets_router_delete_secrets_delegates_to_orchestrator():
    project = _project_for_session_response(session_id="00000000-0000-4000-8000-000000000004")
    project.secrets_json = {"OTHER": "value"}
    secret_orchestrator = AsyncMock()
    secret_orchestrator.delete_secrets.return_value = SimpleNamespace(
        project=project,
        secrets={"OTHER": "value"},
        runtime_synced=False,
        restart_required=True,
    )

    payload = ProjectSecretsDeleteRequest(secret_keys=["API_KEY"])
    result = await delete_session_project_secrets(
        project.session_id,
        payload,
        _user(USER_ID),
        secret_orchestrator,
        None,
    )

    secret_orchestrator.delete_secrets.assert_awaited_once_with(
        None,
        session_id=project.session_id,
        user_id=USER_ID,
        secret_keys=["API_KEY"],
        sync_policy="existing",
    )
    assert result.project_id == UUID(project.id)
    assert result.secrets == {"OTHER": "value"}
    assert result.restart_required is True


def test_project_secrets_request_rejects_invalid_env_var_names():
    with pytest.raises(PydanticValidationError, match="Invalid environment variable name"):
        ProjectSecretsRequest(secrets={"BAD-NAME": "abc"})

    with pytest.raises(PydanticValidationError, match="Invalid environment variable name"):
        ProjectSecretsRequest(secrets={"ALSO\nBAD": "abc"})


def test_project_secrets_delete_request_allows_legacy_invalid_key_names():
    payload = ProjectSecretsDeleteRequest(secret_keys=["BAD-NAME", "ALSO\nBAD", ""])

    assert payload.secret_keys == ["BAD-NAME", "ALSO\nBAD", ""]


@pytest.mark.asyncio
async def test_design_router_proxy_returns_html_and_headers():
    service = AsyncMock()
    service.get_proxy_html.return_value = "<html/>"

    response = await proxy_design_mode(
        _user(USER_ID),
        None,
        service,
        session_id=SESSION_ID,
        url="https://example.com",
    )

    service.get_proxy_html.assert_awaited_once_with(
        None,
        session_id=SESSION_ID,
        user_id=USER_ID,
        url="https://example.com",
    )
    assert response.body == b"<html/>"
    assert (
        response.headers["Content-Security-Policy"]
        == "sandbox allow-scripts allow-forms allow-popups"
    )


@pytest.mark.asyncio
async def test_design_router_ai_change_invokes_service():
    service = AsyncMock()
    service.ai_design_change.return_value = AIChangeResponse(changes=[], explanation="ok")
    request = AIChangeRequest(
        session_id=SESSION_ID,
        element_info=ElementInfoRequest(
            designId="d1",
            tagName="div",
            className="a",
            textContent="text",
            computedStyles={"color": "blue"},
            xpath="/html/body",
        ),
        user_request="make it red",
    )

    result = await ai_change(request, _user(USER_ID), None, service)

    service.ai_design_change.assert_awaited_once_with(
        None,
        user_id=USER_ID,
        request=request,
    )
    assert result.explanation == "ok"


@pytest.mark.asyncio
async def test_design_router_ai_iframe_plan_invokes_service():
    service = AsyncMock()
    service.ai_iframe_plan.return_value = IframeAIPlanResponse(
        operations=[],
        explanation="plan-ready",
        document_snapshot=None,
    )
    request = IframeAIPlanRequest(
        session_id=SESSION_ID,
        user_request="adjust text",
        selected_element=None,
        document_snapshot={
            "version": 1,
            "generatedAt": None,
            "url": "https://example.com",
            "title": "x",
            "nodes": [],
        },
    )

    result = await ai_iframe_plan(request, _user(USER_ID), None, service)
    service.ai_iframe_plan.assert_awaited_once_with(
        None,
        user_id=USER_ID,
        request=request,
    )
    assert result.explanation == "plan-ready"


@pytest.mark.asyncio
async def test_design_router_state_and_sync_routes_delegate():
    state_service = AsyncMock()
    state_service.get_design_state.return_value = DesignStateRequest(
        session_id=SESSION_ID,
        changes=[],
    )
    save_service = AsyncMock()
    save_service.save_design_state.return_value = DesignStateRequest(
        session_id=SESSION_ID,
        changes=[],
    )
    style_changes = [
        StyleChange(
            designId="d1",
            type="text",
            property="value",
            value={},
            timestamp=0,
        )
    ]
    state = await get_design_state(
        SESSION_ID,
        _user(USER_ID),
        None,
        state_service,
    )
    saved = await save_design_state(
        DesignStateRequest(
            session_id=SESSION_ID,
            changes=style_changes,
        ),
        _user(USER_ID),
        None,
        save_service,
    )

    assert state is not None
    assert saved is not None
