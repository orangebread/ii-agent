"""Pydantic schemas (DTOs) for auth domain."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Model for token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthProvidersResponse(BaseModel):
    """Public auth provider availability flags."""

    ii_oauth_available: bool
    google_oauth_available: bool
    dev_auth_bypass_enabled: bool = False


class OpenAIDeviceStartRequest(BaseModel):
    """Request model for starting OpenAI device login."""

    model: str | None = None
    model_reasoning_effort: str | None = None
    search: bool = False


class OpenAIDeviceStartResponse(BaseModel):
    """Response returned when starting OpenAI device login."""

    login_id: str
    verification_url: str
    user_code: str
    interval_seconds: int
    expires_in_seconds: int


class OpenAIDevicePollRequest(BaseModel):
    """Request model for polling OpenAI device login."""

    login_id: str


class OpenAIDevicePollResponse(BaseModel):
    """Status response for OpenAI device login."""

    status: str
    continue_with_ii: bool = False
    pending_connect_id: str | None = None
    error: str | None = None


class TokenPayload(BaseModel):
    """Model for token payload."""

    user_id: UUID
    email: str
    role: str = "user"
    type: str = "access"  # or "refresh"
    exp: datetime
    iat: datetime
