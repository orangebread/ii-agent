"""Sandbox provider capability descriptions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SandboxProviderCapabilities(BaseModel):
    """Backend-owned feature matrix for sandbox providers."""

    commands: bool = False
    python_code: bool = False
    pty: bool = False
    files: bool = False
    file_watch: bool = False
    preview_url: bool = False
    host_discovery: bool = False
    mcp: bool = False
    pause_resume: bool = False
    codex_app_server: bool = False


def resolve_sandbox_provider_capabilities(
    provider: str,
    *,
    settings: Any | None = None,
) -> SandboxProviderCapabilities:
    """Return provider capabilities for UI/runtime gates and smoke assertions."""
    normalized = provider.lower()
    smoke_verified = False
    if settings is not None:
        smoke_verified = bool(getattr(settings, "codex_app_server_smoke_verified", False))

    if normalized == "e2b":
        return SandboxProviderCapabilities(
            commands=True,
            python_code=True,
            pty=True,
            files=True,
            file_watch=True,
            preview_url=True,
            host_discovery=True,
            mcp=True,
            pause_resume=True,
            codex_app_server=smoke_verified,
        )

    if normalized == "docker":
        return SandboxProviderCapabilities(
            commands=True,
            python_code=True,
            pty=True,
            files=True,
            pause_resume=True,
            codex_app_server=True,
        )

    if normalized == "daytona":
        return SandboxProviderCapabilities(
            commands=True,
            python_code=True,
            pty=True,
            files=True,
            file_watch=True,
            preview_url=True,
            host_discovery=True,
            mcp=True,
            pause_resume=True,
            codex_app_server=smoke_verified,
        )

    return SandboxProviderCapabilities()
