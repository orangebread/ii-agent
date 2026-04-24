"""Runtime profile and capability helpers shared across domains."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RuntimeCapabilities(BaseModel):
    """Backend-owned description of workflow/runtime behavior."""

    supports_platform_plan: bool = False
    supports_platform_plan_modification: bool = False
    supports_pause_resume: bool = False
    supports_approvals: bool = False
    supports_user_input: bool = False
    supports_dynamic_tools: bool = False
    supports_connector_injection: bool = False
    supports_sub_agents: bool = False
    supports_persistent_threads: bool = False


class RuntimeProfile(BaseModel):
    """Resolved runtime context for a session or run."""

    runtime_product: str | None = None
    provider: str | None = None
    credential_source: str | None = None
    provider_connection_id: UUID | None = None
    mcp_setting_id: UUID | None = None
    capabilities: RuntimeCapabilities = Field(default_factory=RuntimeCapabilities)


def codex_app_server_workflows_enabled(settings: Any | None = None) -> bool:
    """Return whether Codex App Server workflow features should be advertised."""
    if settings is None:
        from ii_agent.core.config.settings import get_settings

        settings = get_settings()

    if not bool(getattr(settings, "codex_app_server_workflows_enabled", True)):
        return False

    environment = str(getattr(settings, "environment", "") or "").lower()
    smoke_verified = bool(getattr(settings, "codex_app_server_smoke_verified", False))
    sandbox = getattr(settings, "sandbox", None)
    sandbox_provider = str(getattr(sandbox, "provider", "") or "").lower()

    if environment == "production" and not smoke_verified:
        return False

    if sandbox_provider in {"e2b", "daytona"} and not smoke_verified:
        return False

    return True


def resolve_runtime_capabilities(
    runtime_product: str | None,
    *,
    settings: Any | None = None,
) -> RuntimeCapabilities:
    """Return the current workflow capabilities for a runtime product."""
    if runtime_product == "codex":
        if not codex_app_server_workflows_enabled(settings):
            return RuntimeCapabilities()
        return RuntimeCapabilities(
            supports_platform_plan=True,
            supports_platform_plan_modification=True,
            supports_pause_resume=True,
            supports_approvals=True,
            supports_user_input=True,
            supports_dynamic_tools=True,
            supports_persistent_threads=True,
        )

    return RuntimeCapabilities(
        supports_platform_plan=True,
        supports_platform_plan_modification=True,
        supports_pause_resume=True,
        supports_approvals=True,
        supports_user_input=True,
        supports_connector_injection=True,
        supports_sub_agents=True,
    )


def build_runtime_profile(
    *,
    model_config: Any,
    mcp_setting_id: UUID | None = None,
    settings: Any | None = None,
) -> RuntimeProfile:
    """Build a serializable runtime profile from a resolved model config."""
    runtime_product = getattr(model_config, "runtime_product", None)
    provider = getattr(model_config, "provider", None)
    credential_source = getattr(model_config, "credential_source", None)

    return RuntimeProfile(
        runtime_product=runtime_product,
        provider=getattr(provider, "value", provider),
        credential_source=getattr(credential_source, "value", credential_source),
        provider_connection_id=getattr(model_config, "provider_connection_id", None),
        mcp_setting_id=mcp_setting_id,
        capabilities=resolve_runtime_capabilities(runtime_product, settings=settings),
    )
