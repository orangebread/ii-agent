"""Secrets management endpoints for projects."""

import uuid
from typing import Any

from fastapi import APIRouter

from ii_agent.auth.dependencies import CurrentUser, DBSession
from ii_agent.projects.dependencies import (
    ProjectServiceDep,
    ProjectSecretOrchestratorDep,
)
from ii_agent.projects.secrets.schemas import (
    ProjectSecretsDeleteRequest,
    ProjectSecretsRequest,
    ProjectSecretsResponse,
)
from ii_agent.projects.secrets.utils import _decrypt_secrets_payload

router = APIRouter(tags=["Project Secrets"])


def _get_project_secrets(project: Any) -> dict[str, Any]:
    secrets = _decrypt_secrets_payload(project.secrets_json) or {}
    return secrets if isinstance(secrets, dict) else {}


def _build_project_secrets_response(
    *,
    project: Any,
    session_id: uuid.UUID,
    secrets: dict[str, Any],
    restart_required: bool = False,
) -> ProjectSecretsResponse:
    return ProjectSecretsResponse(
        project_id=project.id,
        session_id=session_id,
        secrets=secrets,
        restart_required=restart_required,
        updated_at=project.updated_at,
    )


@router.get("/{session_id}/secrets", response_model=ProjectSecretsResponse)
async def get_session_project_secrets(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    project_service: ProjectServiceDep,
    db: DBSession,
) -> ProjectSecretsResponse:
    """Retrieve decrypted secrets for the user's session project."""
    project = await project_service.get_session_project(
        db,
        session_id=session_id,
        user_id=current_user.id,
    )
    current_secrets = _get_project_secrets(project)
    return _build_project_secrets_response(
        project=project,
        session_id=session_id,
        secrets=current_secrets,
    )


@router.post("/{session_id}/secrets", response_model=ProjectSecretsResponse)
async def set_session_project_secrets(
    session_id: uuid.UUID,
    payload: ProjectSecretsRequest,
    current_user: CurrentUser,
    secret_orchestrator: ProjectSecretOrchestratorDep,
    db: DBSession,
) -> ProjectSecretsResponse:
    """Add or update secrets for the session's project."""
    result = await secret_orchestrator.add_secrets(
        db,
        session_id=session_id,
        user_id=current_user.id,
        secrets=payload.secrets,
        sync_policy="existing",
    )

    return _build_project_secrets_response(
        project=result.project,
        session_id=session_id,
        secrets=result.secrets,
        restart_required=result.restart_required,
    )


@router.put("/{session_id}/secrets", response_model=ProjectSecretsResponse)
async def replace_session_project_secrets(
    session_id: uuid.UUID,
    payload: ProjectSecretsRequest,
    current_user: CurrentUser,
    secret_orchestrator: ProjectSecretOrchestratorDep,
    db: DBSession,
) -> ProjectSecretsResponse:
    """Replace all secrets for the session's project."""
    result = await secret_orchestrator.replace_secrets(
        db,
        session_id=session_id,
        user_id=current_user.id,
        secrets=payload.secrets,
        sync_policy="existing",
    )

    return _build_project_secrets_response(
        project=result.project,
        session_id=session_id,
        secrets=result.secrets,
        restart_required=result.restart_required,
    )


@router.delete("/{session_id}/secrets", response_model=ProjectSecretsResponse)
async def delete_session_project_secrets(
    session_id: uuid.UUID,
    payload: ProjectSecretsDeleteRequest,
    current_user: CurrentUser,
    secret_orchestrator: ProjectSecretOrchestratorDep,
    db: DBSession,
) -> ProjectSecretsResponse:
    """Delete selected secrets from the session's project."""
    result = await secret_orchestrator.delete_secrets(
        db,
        session_id=session_id,
        user_id=current_user.id,
        secret_keys=payload.secret_keys,
        sync_policy="existing",
    )

    return _build_project_secrets_response(
        project=result.project,
        session_id=session_id,
        secrets=result.secrets,
        restart_required=result.restart_required,
    )
