from __future__ import annotations

from types import SimpleNamespace

import pytest

from ii_agent.core.runtime_capabilities import resolve_runtime_capabilities
from ii_agent.agents.sandboxes.capabilities import resolve_sandbox_provider_capabilities


pytestmark = pytest.mark.unit


def _settings(
    *,
    environment: str = "dev",
    sandbox_provider: str = "docker",
    workflows_enabled: bool = True,
    smoke_verified: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        environment=environment,
        codex_app_server_workflows_enabled=workflows_enabled,
        codex_app_server_smoke_verified=smoke_verified,
        sandbox=SimpleNamespace(provider=sandbox_provider),
    )


def test_codex_capabilities_are_enabled_for_local_docker_runtime_by_default():
    caps = resolve_runtime_capabilities("codex", settings=_settings())

    assert caps.supports_platform_plan is True
    assert caps.supports_dynamic_tools is True
    assert caps.supports_approvals is True


def test_codex_capabilities_are_disabled_when_workflow_flag_is_off():
    caps = resolve_runtime_capabilities(
        "codex",
        settings=_settings(workflows_enabled=False),
    )

    assert caps.supports_platform_plan is False
    assert caps.supports_dynamic_tools is False
    assert caps.supports_approvals is False


def test_codex_capabilities_are_disabled_for_unverified_e2b_template():
    caps = resolve_runtime_capabilities(
        "codex",
        settings=_settings(sandbox_provider="e2b", smoke_verified=False),
    )

    assert caps.supports_platform_plan is False
    assert caps.supports_dynamic_tools is False
    assert caps.supports_approvals is False


def test_codex_capabilities_are_disabled_for_unverified_daytona_runtime():
    caps = resolve_runtime_capabilities(
        "codex",
        settings=_settings(sandbox_provider="daytona", smoke_verified=False),
    )

    assert caps.supports_platform_plan is False
    assert caps.supports_dynamic_tools is False
    assert caps.supports_approvals is False


def test_codex_capabilities_require_smoke_verification_in_production():
    unverified = resolve_runtime_capabilities(
        "codex",
        settings=_settings(environment="production", sandbox_provider="docker"),
    )
    verified = resolve_runtime_capabilities(
        "codex",
        settings=_settings(
            environment="production",
            sandbox_provider="docker",
            smoke_verified=True,
        ),
    )

    assert unverified.supports_platform_plan is False
    assert verified.supports_platform_plan is True
    assert verified.supports_dynamic_tools is True


def test_daytona_sandbox_capability_matrix_requires_codex_smoke_for_app_server():
    unverified = resolve_sandbox_provider_capabilities(
        "daytona",
        settings=_settings(sandbox_provider="daytona", smoke_verified=False),
    )
    verified = resolve_sandbox_provider_capabilities(
        "daytona",
        settings=_settings(sandbox_provider="daytona", smoke_verified=True),
    )

    assert unverified.commands is True
    assert unverified.file_watch is True
    assert unverified.preview_url is True
    assert unverified.codex_app_server is False
    assert verified.codex_app_server is True
