"""Sandbox configuration settings."""

from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Constants
_DEFAULT_SANDBOX_TIMEOUT_SECONDS = 7200  # 2 hours

# Type aliases
SandboxProvider = Literal["e2b", "docker", "daytona", "local"]


class SandboxSettings(BaseSettings):
    """Sandbox environment configuration.

    Environment variables use SANDBOX_ prefix:
        SANDBOX_PROVIDER: Sandbox provider ("daytona", "e2b", "docker", "local")
        SANDBOX_E2B_API_KEY: E2B API key
        SANDBOX_E2B_TEMPLATE_ID: E2B template ID
        SANDBOX_DAYTONA_API_URL: Daytona API URL
        SANDBOX_DAYTONA_API_KEY: Daytona API key
        SANDBOX_DAYTONA_TARGET: Daytona target
        SANDBOX_TIMEOUT_SECONDS: Sandbox timeout in seconds
        SANDBOX_AUTO_PAUSE: Whether to auto-pause on inactivity
        SANDBOX_USER: Default user path
        SANDBOX_SERVER_URL: Sandbox server URL

    Example .env:
        SANDBOX_PROVIDER=daytona
        SANDBOX_DAYTONA_API_URL=http://localhost:3980/api
        SANDBOX_TIMEOUT_SECONDS=7200
        SANDBOX_AUTO_PAUSE=true
    """

    model_config = SettingsConfigDict(
        env_prefix="SANDBOX_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider settings
    provider: SandboxProvider = Field(
        default="daytona",
        description="Sandbox provider to use (e2b, docker, daytona, or local)",
    )

    timeout_seconds: int = Field(
        default=_DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        description="Sandbox session timeout in seconds",
        gt=0,
    )

    # E2B-specific settings
    e2b_api_key: Optional[str] = Field(
        default=None,
        description="E2B API key (required when using E2B provider)",
    )

    docker_image: str = Field(
        default="ii-agent-codex-sandbox:local",
        description="Container image used when using the Docker sandbox provider",
    )

    codex_cli_version: str = Field(
        default="0.124.0",
        description=(
            "Pinned @openai/codex CLI version installed into local Docker sandbox images. "
            "This must support `codex app-server`."
        ),
    )

    e2b_template_id: str = Field(
        default="base",
        description="E2B template ID for custom sandbox environments",
    )

    e2b_domain: Optional[str] = Field(
        default=None,
        description="E2B custom domain (None uses E2B default)",
    )

    # Daytona-specific settings
    daytona_api_url: str = Field(
        default="http://localhost:3980/api",
        description="Daytona API URL for self-hosted or managed Daytona",
    )

    daytona_api_key: Optional[str] = Field(
        default=None,
        description="Daytona API key or admin key when required by the Daytona deployment",
    )

    daytona_target: Optional[str] = Field(
        default=None,
        description="Daytona target environment/region",
    )

    daytona_default_image: str = Field(
        default="ii-agent-codex-sandbox:local",
        description="Container image used to create Daytona sandboxes when no snapshot is configured",
    )

    daytona_snapshot: Optional[str] = Field(
        default=None,
        description="Daytona snapshot name or ID used instead of building from an image",
    )

    daytona_auto_stop_interval: int = Field(
        default=15,
        description="Daytona auto-stop interval in minutes; 0 disables auto-stop when supported",
        ge=0,
    )

    daytona_ephemeral: bool = Field(
        default=True,
        description="Request auto-delete behavior for Daytona sandboxes after the configured timeout",
    )

    daytona_public_preview: bool = Field(
        default=True,
        description="Create Daytona sandboxes with public preview URLs",
    )

    daytona_network_block_all: bool = Field(
        default=False,
        description="Block all outbound network access for Daytona sandboxes",
    )

    daytona_network_allow_list: list[str] = Field(
        default_factory=list,
        description="Comma-joined Daytona network allow list entries",
    )

    extended_timeout_seconds: int = Field(
        default=14400,
        description="Extended timeout for reconnecting paused sandboxes (4 hours)",
        gt=0,
    )

    auto_pause: bool = Field(
        default=True,
        description="Auto-pause sandbox on inactivity to save resources",
    )

    # Sandbox environment settings
    user: str = Field(
        default="/home/user",
        description="Default user home directory in sandbox",
    )

    template_id: Optional[str] = Field(
        default=None,
        description="Sandbox template ID (legacy field)",
    )

    server_url: str = Field(
        default="http://localhost:8100",
        description="Sandbox server URL for API communication",
    )

    time_til_clean_up: int = Field(
        default=45 * 60,
        description="Time in seconds until sandbox cleanup (default 45 minutes)",
        gt=0,
    )

    def validate_for_provider(self) -> None:
        """Validate configuration for the selected provider.

        Raises:
            ValueError: If required configuration is missing for the provider.
        """
        if self.provider == "e2b" and not self.e2b_api_key:
            raise ValueError(
                "E2B API key is required when using E2B provider. "
                "Set SANDBOX_E2B_API_KEY environment variable."
            )
        if self.provider == "daytona" and not self.daytona_api_url:
            raise ValueError(
                "Daytona API URL is required when using Daytona provider. "
                "Set SANDBOX_DAYTONA_API_URL environment variable."
            )
