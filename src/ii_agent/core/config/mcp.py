"""Model Context Protocol (MCP) configuration."""

from typing import Any, Dict, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    """MCP (Model Context Protocol) server configuration.

    Environment variables use MCP_ prefix:
        MCP_PORT: MCP server port
        MCP_TIMEOUT: MCP operation timeout in seconds
        MCP_OAUTH_CLIENT_ID: OAuth client ID for MCP authentication
        MCP_OAUTH_CLIENT_SECRET: OAuth client secret
        MCP_II_CLIENT_ID: External OAuth client ID (optional)
        MCP_II_SCOPE: OAuth scopes for external authentication

    Example .env:
        MCP_PORT=6060
        MCP_TIMEOUT=1800
        MCP_OAUTH_CLIENT_ID=your-client-id
        MCP_OAUTH_CLIENT_SECRET=your-client-secret
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MCP server configuration
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="MCP server configuration dictionary",
    )

    port: int = Field(
        default=6060,
        description="MCP server port",
        ge=1,
        le=65535,
    )

    timeout: int = Field(
        default=1800,
        description="MCP operation timeout in seconds (30 minutes default)",
        gt=0,
    )

    # MCP OAuth Client Credentials (for ChatGPT and other MCP clients)
    oauth_client_id: str = Field(
        default="",
        description="OAuth Client ID for MCP endpoint authentication",
    )

    oauth_client_secret: str = Field(
        default="",
        description="OAuth Client Secret for MCP endpoint authentication",
    )

    # MCP OAuth Provider Configuration (optional external OAuth like ii.inc)
    ii_client_id: str = Field(
        default="",
        description="OAuth Client ID for MCP external OAuth provider (leave empty to use frontend login)",
    )

    ii_scope: str = Field(
        default="openid offline profile email",
        description="OAuth scopes for MCP external authentication",
    )

    oauth_token_expiry: int = Field(
        default=60 * 60 * 24 * 30,  # 30 days
        description="OAuth token expiry in seconds",
        gt=0,
    )

    # Anthropic Console OAuth (for MCP server token exchange)
    anthropic_oauth_authorize_url: str = Field(
        default="https://claude.ai/oauth/authorize",
        description="Anthropic OAuth authorization endpoint",
    )

    anthropic_oauth_token_url: str = Field(
        default="https://console.anthropic.com/v1/oauth/token",
        description="Anthropic console OAuth token exchange endpoint",
    )

    anthropic_oauth_client_id: str = Field(
        default="9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        description="Anthropic console OAuth client ID",
    )

    anthropic_oauth_redirect_uri: str = Field(
        default="https://console.anthropic.com/oauth/code/callback",
        description="Anthropic console OAuth redirect URI",
    )

    openai_oauth_issuer: str = Field(
        default="https://auth.openai.com",
        description="OpenAI auth issuer used for Codex ChatGPT OAuth flows",
    )

    openai_oauth_client_id: str = Field(
        default="app_EMoamEEZ73f0CkXaXp7hrann",
        description="OpenAI Codex client ID used for ChatGPT-backed Codex auth flows",
    )

    def has_oauth_credentials(self) -> bool:
        """Check if MCP OAuth credentials are configured."""
        return bool(self.oauth_client_id and self.oauth_client_secret)

    def has_external_oauth(self) -> bool:
        """Check if external OAuth provider is configured."""
        return bool(self.ii_client_id)
