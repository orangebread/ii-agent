"""Unit tests for sessions router endpoints using FastAPI TestClient."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ii_agent.auth.dependencies import get_current_user
from ii_agent.core.dependencies import _db_session_dependency
from ii_agent.core.exceptions import IIAgentError
from ii_agent.core.middleware import ii_agent_error_handler
from ii_agent.settings.mcp.dependencies import _get_mcp_setting_service as get_mcp_setting_service
from ii_agent.settings.mcp.exceptions import MCPSettingNotFoundError
from ii_agent.sessions.dependencies import _get_run_task_service
from ii_agent.files.dependencies import _get_file_service as get_file_service
from ii_agent.sessions.dependencies import (
    _get_session_fork_service as get_session_fork_service,
    _get_session_service as get_session_service,
)
from ii_agent.sessions.router import public_router, router
from ii_agent.sessions.schemas import SessionEventDetail, SessionInfo

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())
_SESSION_ID = str(uuid.uuid4())


def _make_user(user_id: str = _USER_ID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email="test@example.com", is_active=True)


def _make_session_data(session_id: str = _SESSION_ID, **kwargs) -> SessionInfo:
    defaults = dict(
        id=uuid.UUID(session_id),
        user_id=_USER_ID,
        name="Test Session",
        status="active",
        workspace_dir="/workspace",
        is_public=False,
        created_at="2026-01-01T00:00:00",
        updated_at=None,
        last_message_at=None,
        agent_type="chat",
        api_version=None,
        sandbox_id=None,
        public_url=None,
        token_usage=None,
        settings=None,
        project_id=None,
    )
    defaults.update(kwargs)
    return SessionInfo(**defaults)


def _make_session_service(
    *,
    session_data: dict | None = None,
    sessions_list: list | None = None,
    total: int = 0,
    events: list | None = None,
    files: list | None = None,
    public_session_data: dict | None = None,
    bulk_delete_result: tuple | None = None,
    set_public_result: bool = True,
    updated_session_data: dict | None = None,
) -> MagicMock:
    svc = MagicMock()
    svc.get_session_details = AsyncMock(return_value=session_data)
    svc.get_user_sessions = AsyncMock(return_value=(sessions_list or [], total))
    svc.get_session_events_with_details = AsyncMock(return_value=events or [])
    svc.get_public_session_details = AsyncMock(return_value=public_session_data)
    svc.bulk_soft_delete_sessions = AsyncMock(return_value=bulk_delete_result or ([], []))
    svc.set_session_public = AsyncMock(return_value=set_public_result)
    svc.soft_delete_session = AsyncMock(return_value=None)
    svc.update_session_name = AsyncMock(return_value=None)
    svc.update_session_fields = AsyncMock(return_value=None)
    svc.update_session_plan = AsyncMock(return_value=None)

    # second call for get_session_details in update_session
    if updated_session_data is not None:
        svc.get_session_details = AsyncMock(side_effect=[session_data, updated_session_data])

    return svc


def _make_run_task_service(*, last_task=None) -> MagicMock:
    svc = MagicMock()
    svc.get_last_by_session_id = AsyncMock(return_value=last_task)
    return svc


def _make_file_service(*, files: list | None = None) -> MagicMock:
    svc = MagicMock()
    svc.get_files_by_session_id = AsyncMock(return_value=files or [])
    return svc


def _make_fork_service(*, fork_result: dict | None = None) -> MagicMock:
    from ii_agent.sessions.schemas import ForkSessionResponse, SandboxMode

    svc = MagicMock()
    result = fork_result or ForkSessionResponse(
        session_id=str(uuid.uuid4()),
        parent_session_id=_SESSION_ID,
        name="Forked Session",
        agent_type="research_to_website",
        sandbox_id=None,
        sandbox_mode=SandboxMode.SHARE,
    )
    svc.fork_session = AsyncMock(return_value=result)
    return svc


def _make_mcp_service() -> MagicMock:
    svc = MagicMock()
    svc.assert_runtime_setting_selectable = AsyncMock(return_value=None)
    return svc


def _build_app(
    session_service: MagicMock,
    run_task_service: MagicMock | None = None,
    file_service: MagicMock | None = None,
    fork_service: MagicMock | None = None,
    mcp_service: MagicMock | None = None,
    user: SimpleNamespace | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(IIAgentError, ii_agent_error_handler)

    _user = user or _make_user()
    _run_task_svc = run_task_service or _make_run_task_service()
    _file_svc = file_service or _make_file_service()
    _fork_svc = fork_service or _make_fork_service()
    _mcp_svc = mcp_service or _make_mcp_service()

    app.dependency_overrides[get_current_user] = lambda: _user
    app.dependency_overrides[_db_session_dependency] = lambda: AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[_get_run_task_service] = lambda: _run_task_svc
    app.dependency_overrides[get_file_service] = lambda: _file_svc
    app.dependency_overrides[get_session_fork_service] = lambda: _fork_svc
    app.dependency_overrides[get_mcp_setting_service] = lambda: _mcp_svc

    return app


# ---------------------------------------------------------------------------
# Tests – POST /sessions/bulk-delete
# ---------------------------------------------------------------------------


def test_bulk_delete_sessions_success():
    """Arrange: two session IDs; Act: POST bulk-delete; Assert: deleted_ids returned."""
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    svc = _make_session_service(bulk_delete_result=(ids, []))

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.post("/sessions/bulk-delete", json={"session_ids": ids})

    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_ids"] == ids
    assert data["failed_ids"] == []


def test_bulk_delete_sessions_partial_failure():
    """Arrange: one success, one failure; Assert: both lists populated."""
    success_id = str(uuid.uuid4())
    failed_id = str(uuid.uuid4())
    svc = _make_session_service(bulk_delete_result=([success_id], [failed_id]))

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.post(
        "/sessions/bulk-delete",
        json={"session_ids": [success_id, failed_id]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert success_id in data["deleted_ids"]
    assert failed_id in data["failed_ids"]


# ---------------------------------------------------------------------------
# Tests – GET /sessions/{session_id}
# ---------------------------------------------------------------------------


def test_get_session_success():
    """Arrange: session exists; Act: GET session; Assert: 200 with session data."""
    session_data = _make_session_data()
    svc = _make_session_service(session_data=session_data)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _SESSION_ID
    assert data["status"] == "active"


def test_get_session_not_found_returns_404():
    """Arrange: session not found; Act: GET session; Assert: 404."""
    svc = _make_session_service(session_data=None)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/sessions/{_SESSION_ID}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests – GET /sessions (list)
# ---------------------------------------------------------------------------


def test_list_sessions_returns_paginated_results():
    """Arrange: two sessions; Act: GET /sessions; Assert: list with total."""
    sessions = [_make_session_data(), _make_session_data(str(uuid.uuid4()))]
    svc = _make_session_service(sessions_list=sessions, total=2)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.get("/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["sessions"]) == 2
    assert data["page"] == 1
    assert data["per_page"] == 20


def test_list_sessions_with_search_query():
    """Arrange: query param; Assert: service called with search_term."""
    svc = _make_session_service(sessions_list=[], total=0)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.get("/sessions?query=test&page=2&per_page=5")

    assert resp.status_code == 200
    call_kwargs = svc.get_user_sessions.call_args.kwargs
    assert call_kwargs["search_term"] == "test"
    assert call_kwargs["page"] == 2
    assert call_kwargs["per_page"] == 5


def test_list_sessions_with_session_type_filter():
    """Arrange: session_type param; Assert: service called with session_type."""
    svc = _make_session_service(sessions_list=[], total=0)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.get("/sessions?session_type=chat")

    assert resp.status_code == 200
    call_kwargs = svc.get_user_sessions.call_args.kwargs
    assert call_kwargs["session_type"] == "chat"


def test_list_sessions_public_only_filter():
    """Arrange: public_only=true; Assert: service called with public_only=True."""
    svc = _make_session_service(sessions_list=[], total=0)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.get("/sessions?public_only=true")

    assert resp.status_code == 200
    call_kwargs = svc.get_user_sessions.call_args.kwargs
    assert call_kwargs["public_only"] is True


# ---------------------------------------------------------------------------
# Tests – GET /sessions/{session_id}/events
# ---------------------------------------------------------------------------


def _make_event_data(session_id: str = _SESSION_ID) -> SessionEventDetail:
    """Build a SessionEventDetail matching what the service returns."""
    return SessionEventDetail(
        id=uuid.uuid4(),
        session_id=uuid.UUID(session_id),
        created_at="2026-01-01T00:00:00",
        type="message",
        content={},
        workspace_dir="/workspace",
        run_id=None,
    )


def test_get_session_events_returns_events_and_run_status():
    """Arrange: session with events and last task; Assert: events list returned."""
    session_data = _make_session_data()
    events_raw = [_make_event_data()]
    last_task = SimpleNamespace(status="completed")
    svc = _make_session_service(session_data=session_data, events=events_raw)
    agent_svc = _make_run_task_service(last_task=last_task)

    app = _build_app(svc, run_task_service=agent_svc)
    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}/events")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_status"] == "completed"
    assert len(data["events"]) == 1


def test_get_session_events_not_found_returns_404():
    """Arrange: session not found; Assert: 404."""
    svc = _make_session_service(session_data=None)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/sessions/{_SESSION_ID}/events")

    assert resp.status_code == 404


def test_get_session_events_run_status_failure_handled():
    """Arrange: agent service raises; Assert: events returned with run_status=None."""
    session_data = _make_session_data()
    svc = _make_session_service(session_data=session_data, events=[])
    agent_svc = _make_run_task_service()
    agent_svc.get_last_by_session_id = AsyncMock(side_effect=Exception("DB error"))

    app = _build_app(svc, run_task_service=agent_svc)
    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}/events")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_status"] is None


# ---------------------------------------------------------------------------
# Tests – GET /sessions/{session_id}/files
# ---------------------------------------------------------------------------


def test_get_session_files_returns_files():
    """Arrange: session with files; Act: GET files; Assert: file list returned."""
    session_data = _make_session_data()
    file_id = str(uuid.uuid4())
    files = [
        SimpleNamespace(
            id=file_id,
            name="test.pdf",
            size=1024,
            content_type="application/pdf",
            url="https://example.com/test.pdf",
        )
    ]
    svc = _make_session_service(session_data=session_data)
    file_svc = _make_file_service(files=files)

    app = _build_app(svc, file_service=file_svc)
    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}/files")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == file_id
    assert data[0]["name"] == "test.pdf"


def test_get_session_files_session_not_found():
    """Arrange: session not found; Assert: 404."""
    svc = _make_session_service(session_data=None)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/sessions/{_SESSION_ID}/files")

    assert resp.status_code == 404


def test_get_session_files_empty_list():
    """Arrange: session with no files; Assert: empty list returned."""
    svc = _make_session_service(session_data=_make_session_data())
    file_svc = _make_file_service(files=[])

    app = _build_app(svc, file_service=file_svc)
    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}/files")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Tests – POST /sessions/{session_id}/publish
# ---------------------------------------------------------------------------


def test_publish_session_success():
    """Arrange: valid session; Act: POST publish; Assert: success message."""
    svc = _make_session_service(set_public_result=True)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.post(f"/sessions/{_SESSION_ID}/publish")

    assert resp.status_code == 200
    data = resp.json()
    assert "published" in data["message"].lower()
    svc.set_session_public.assert_called_once()
    call_args = svc.set_session_public.call_args
    assert call_args.args[3] is True  # is_public=True


def test_publish_session_not_found():
    """Arrange: session not found; Assert: 404."""
    svc = _make_session_service(set_public_result=False)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(f"/sessions/{_SESSION_ID}/publish")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests – POST /sessions/{session_id}/unpublish
# ---------------------------------------------------------------------------


def test_unpublish_session_success():
    """Arrange: valid session; Act: POST unpublish; Assert: success message."""
    svc = _make_session_service(set_public_result=True)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.post(f"/sessions/{_SESSION_ID}/unpublish")

    assert resp.status_code == 200
    data = resp.json()
    assert "unpublished" in data["message"].lower()
    call_args = svc.set_session_public.call_args
    assert call_args.args[3] is False  # is_public=False


def test_unpublish_session_not_found():
    """Arrange: session not found; Assert: 404."""
    svc = _make_session_service(set_public_result=False)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(f"/sessions/{_SESSION_ID}/unpublish")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests – GET /sessions/{session_id}/public
# ---------------------------------------------------------------------------


def test_get_public_session_no_auth():
    """Arrange: public session exists; Act: GET public; Assert: 200 without auth."""
    public_data = _make_session_data(is_public=True)
    svc = _make_session_service(public_session_data=public_data)

    # Build app without CurrentUser override (public endpoint)
    app = FastAPI()
    app.include_router(public_router)
    app.add_exception_handler(IIAgentError, ii_agent_error_handler)
    app.dependency_overrides[_db_session_dependency] = lambda: AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[_get_run_task_service] = lambda: _make_run_task_service()

    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _SESSION_ID


def test_get_public_session_not_found():
    """Arrange: session not public; Assert: 404."""
    svc = _make_session_service(public_session_data=None)

    app = FastAPI()
    app.include_router(public_router)
    app.add_exception_handler(IIAgentError, ii_agent_error_handler)
    app.dependency_overrides[_db_session_dependency] = lambda: AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[_get_run_task_service] = lambda: _make_run_task_service()

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/sessions/{_SESSION_ID}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests – GET /sessions/{session_id}/public/events
# ---------------------------------------------------------------------------


def test_get_public_session_events_success():
    """Arrange: public session with events; Assert: events returned."""
    public_data = _make_session_data()
    events_raw = [_make_event_data()]
    svc = _make_session_service(public_session_data=public_data, events=events_raw)
    agent_svc = _make_run_task_service(last_task=SimpleNamespace(status="completed"))

    app = FastAPI()
    app.include_router(public_router)
    app.add_exception_handler(IIAgentError, ii_agent_error_handler)
    app.dependency_overrides[_db_session_dependency] = lambda: AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[_get_run_task_service] = lambda: agent_svc
    app.dependency_overrides[get_file_service] = lambda: _make_file_service()

    client = TestClient(app)
    resp = client.get(f"/sessions/{_SESSION_ID}/events")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 1


# ---------------------------------------------------------------------------
# Tests – DELETE /sessions/{session_id}
# ---------------------------------------------------------------------------


def test_delete_session_success():
    """Arrange: valid session; Act: DELETE; Assert: success message."""
    svc = _make_session_service()

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.delete(f"/sessions/{_SESSION_ID}")

    assert resp.status_code == 200
    data = resp.json()
    assert "deleted" in data["message"].lower()
    svc.soft_delete_session.assert_called_once()


# ---------------------------------------------------------------------------
# Tests – POST /sessions/{session_id}/fork
# ---------------------------------------------------------------------------


def test_fork_session_success():
    """Arrange: valid fork request; Act: POST fork; Assert: new session returned."""
    fork_svc = _make_fork_service()
    svc = _make_session_service()

    app = _build_app(svc, fork_service=fork_svc)
    client = TestClient(app)
    resp = client.post(
        f"/sessions/{_SESSION_ID}/fork",
        json={
            "fork_type": "research_to_website",
            "sandbox_mode": "share",
            "context": {
                "attachments": ["file.html"],
                "additional_instruction": None,
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_session_id"] == _SESSION_ID
    fork_svc.fork_session.assert_called_once()


# ---------------------------------------------------------------------------
# Tests – PATCH /sessions/{session_id}
# ---------------------------------------------------------------------------


def test_update_session_name_success():
    """Arrange: valid session; Act: PATCH with name; Assert: updated session returned."""
    original = _make_session_data()
    updated = _make_session_data(name="Updated Name")
    svc = _make_session_service(session_data=original, updated_session_data=updated)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.patch(f"/sessions/{_SESSION_ID}", json={"name": "Updated Name"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    svc.update_session_name.assert_called_once()


def test_update_session_not_found():
    """Arrange: session not found; Assert: 404."""
    svc = _make_session_service(session_data=None)

    app = _build_app(svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.patch(f"/sessions/{_SESSION_ID}", json={"name": "New Name"})

    assert resp.status_code == 404


def test_update_session_no_name_change():
    """Arrange: payload with no name; Assert: update_session_name not called."""
    session_data = _make_session_data()
    svc = _make_session_service(session_data=session_data, updated_session_data=session_data)

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.patch(f"/sessions/{_SESSION_ID}", json={})

    assert resp.status_code == 200
    svc.update_session_name.assert_not_called()


def test_update_session_validates_runtime_override_before_persisting():
    """Arrange: MCP override provided; Act: PATCH; Assert: selection is validated first."""
    session_data = _make_session_data()
    updated = _make_session_data(mcp_setting_id=uuid.uuid4())
    svc = _make_session_service(session_data=session_data, updated_session_data=updated)
    mcp_svc = _make_mcp_service()
    setting_id = str(uuid.uuid4())

    app = _build_app(svc, mcp_service=mcp_svc)
    client = TestClient(app)
    resp = client.patch(f"/sessions/{_SESSION_ID}", json={"mcp_setting_id": setting_id})

    assert resp.status_code == 200
    mcp_svc.assert_runtime_setting_selectable.assert_awaited_once()
    svc.update_session_fields.assert_called_once()
    call_kwargs = svc.update_session_fields.call_args.kwargs
    assert str(call_kwargs["mcp_setting_id"]) == setting_id


def test_update_session_rejects_invalid_runtime_override():
    """Arrange: invalid MCP override; Act: PATCH; Assert: no session update is persisted."""
    session_data = _make_session_data()
    svc = _make_session_service(session_data=session_data, updated_session_data=session_data)
    mcp_svc = _make_mcp_service()
    mcp_svc.assert_runtime_setting_selectable.side_effect = MCPSettingNotFoundError("missing")

    app = _build_app(svc, mcp_service=mcp_svc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.patch(f"/sessions/{_SESSION_ID}", json={"mcp_setting_id": str(uuid.uuid4())})

    assert resp.status_code == 404
    svc.update_session_fields.assert_not_called()


# ---------------------------------------------------------------------------
# Tests – PATCH /sessions/{session_id}/plan
# ---------------------------------------------------------------------------


def test_update_session_plan_success():
    """Arrange: valid plan payload; Act: PATCH plan; Assert: success message."""
    svc = _make_session_service()

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.patch(
        f"/sessions/{_SESSION_ID}/plan",
        json={
            "summary": "Phase 1 complete",
            "milestones": [
                {
                    "id": str(uuid.uuid4()),
                    "content": "Setup done",
                    "status": "completed",
                }
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "updated" in data["message"].lower()
    svc.update_session_plan.assert_called_once()


def test_update_session_plan_empty_milestones():
    """Arrange: empty milestones; Assert: 200 with empty list."""
    svc = _make_session_service()

    app = _build_app(svc)
    client = TestClient(app)
    resp = client.patch(
        f"/sessions/{_SESSION_ID}/plan",
        json={"summary": "Summary", "milestones": []},
    )

    assert resp.status_code == 200
    call_kwargs = svc.update_session_plan.call_args.kwargs
    assert call_kwargs["milestones"] == []
