"""Secret key definitions for GCP Secret Manager integration."""

from enum import Enum


class SecretKey(str, Enum):
    """Mapping of application secrets to GCP Secret Manager names.

    Each enum value is the GCP secret name suffix (without prefix).
    The full GCP secret name is: {prefix}-{value}

    Example:
        With prefix "ii-agent":
        SecretKey.DATABASE_URL -> "ii-agent-database-url"
    """

    DATABASE_URL = "database-url"
    REDIS_SESSION_URL = "redis-url"
    GOOGLE_CLIENT_SECRET = "google-client-secret"
    GITHUB_CLIENT_SECRET = "github-client-secret"
    REVENUECAT_CLIENT_SECRET = "revenuecat-client-secret"
    GITHUB_APP_PRIVATE_KEY = "github-app-private-key"
    SESSION_SECRET_KEY = "session-secret-key"
    STRIPE_SECRET_KEY = "stripe-secret-key"
    STRIPE_WEBHOOK_SECRET = "stripe-webhook-secret"
    SANDBOX_E2B_API_KEY = "e2b-api-key"
    SANDBOX_DAYTONA_API_KEY = "daytona-api-key"
    MCP_OAUTH_CLIENT_SECRET = "mcp-oauth-client-secret"
    COMPOSIO_API_KEY = "composio-api-key"
    COMPOSIO_ENCRYPTION_KEY = "composio-encryption-key"
    COMPOSIO_WEBHOOK_SECRET = "composio-webhook-secret"
    JWT_SECRET_KEY = "jwt-secret-key"
    ENCRYPTION_KEY = "encryption-key"
    A2A_SANDBOX_API_KEY = "a2a-sandbox-api-key"

    def to_gcp_name(self, prefix: str = "ii-agent") -> str:
        """Get full GCP Secret Manager secret name.

        Args:
            prefix: Secret name prefix (e.g., "ii-agent")

        Returns:
            Full secret name like "ii-agent-database-url"
        """
        return f"{prefix}-{self.value}"

    def to_env_var(self) -> str:
        """Get corresponding environment variable name.

        Returns:
            Environment variable name like "DATABASE_URL"
        """
        return self.name


# Grouped constants for bulk operations
DATABASE_SECRETS = {SecretKey.DATABASE_URL, SecretKey.REDIS_SESSION_URL}

OAUTH_SECRETS = {
    SecretKey.GOOGLE_CLIENT_SECRET,
    SecretKey.GITHUB_CLIENT_SECRET,
    SecretKey.REVENUECAT_CLIENT_SECRET,
    SecretKey.GITHUB_APP_PRIVATE_KEY,
    SecretKey.SESSION_SECRET_KEY,
    SecretKey.MCP_OAUTH_CLIENT_SECRET,
}

BILLING_SECRETS = {SecretKey.STRIPE_SECRET_KEY, SecretKey.STRIPE_WEBHOOK_SECRET}

LLM_SECRETS = {SecretKey.JWT_SECRET_KEY}

TOOL_SERVER_SECRETS = {
    SecretKey.SANDBOX_E2B_API_KEY,
    SecretKey.SANDBOX_DAYTONA_API_KEY,
    SecretKey.A2A_SANDBOX_API_KEY,
}

COMPOSIO_SECRETS = {
    SecretKey.COMPOSIO_API_KEY,
    SecretKey.COMPOSIO_ENCRYPTION_KEY,
    SecretKey.COMPOSIO_WEBHOOK_SECRET,
}

ALL_SECRETS = (
    DATABASE_SECRETS
    | OAUTH_SECRETS
    | BILLING_SECRETS
    | LLM_SECRETS
    | TOOL_SERVER_SECRETS
    | COMPOSIO_SECRETS
)
