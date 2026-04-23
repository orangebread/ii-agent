from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from ii_agent.core.exceptions import ValidationError as CoreValidationError
from ii_agent.projects.secrets.utils import validate_env_var_names


class ProjectSecretsRequest(BaseModel):
    """Payload for adding or updating secrets on a project."""

    secrets: Dict[str, Any]

    @field_validator("secrets")
    @classmethod
    def validate_secret_keys(cls, secrets: Dict[str, Any]) -> Dict[str, Any]:
        try:
            validate_env_var_names(secrets)
        except CoreValidationError as exc:
            raise ValueError(exc.message) from exc
        return secrets


class ProjectSecretsDeleteRequest(BaseModel):
    """Payload for deleting specific secrets from a project."""

    secret_keys: list[str]


class ProjectSecretsResponse(BaseModel):
    """Response containing decrypted secrets for a project session."""

    project_id: UUID
    session_id: UUID
    secrets: Dict[str, Any]
    restart_required: bool = False
    updated_at: Optional[datetime]
