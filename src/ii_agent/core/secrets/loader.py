"""Secret loading utilities.

The SECRET_TO_SETTINGS mapping is kept here as a reference for which secrets
map to which Settings fields. The actual loading is now handled by
GCPSecretManagerSource (a custom Pydantic settings source) during Settings
construction — no post-construction mutation needed.
"""

import logging

from ii_agent.core.secrets.keys import ALL_SECRETS, SecretKey
from ii_agent.core.secrets.provider import SecretProvider

logger = logging.getLogger(__name__)

# Mapping from SecretKey to the Settings field path.
# Format: SecretKey -> (nested_attr, field_name) or (None, field_name) for top-level.
# This mapping is authoritative; gcp_source.py mirrors it as plain strings to
# avoid circular imports.
SECRET_TO_SETTINGS: dict[SecretKey, tuple[str | None, str]] = {
    SecretKey.DATABASE_URL: ("database", "url"),
    SecretKey.REDIS_SESSION_URL: ("redis", "session_url"),
    SecretKey.GOOGLE_CLIENT_SECRET: ("oauth", "google_client_secret"),
    SecretKey.GITHUB_CLIENT_SECRET: ("oauth", "github_client_secret"),
    SecretKey.REVENUECAT_CLIENT_SECRET: ("oauth", "revenuecat_client_secret"),
    SecretKey.GITHUB_APP_PRIVATE_KEY: ("oauth", "github_app_private_key"),
    SecretKey.SESSION_SECRET_KEY: ("oauth", "session_secret_key"),
    SecretKey.STRIPE_SECRET_KEY: ("stripe", "secret_key"),
    SecretKey.STRIPE_WEBHOOK_SECRET: ("stripe", "webhook_secret"),
    SecretKey.SANDBOX_E2B_API_KEY: ("sandbox", "e2b_api_key"),
    SecretKey.SANDBOX_DAYTONA_API_KEY: ("sandbox", "daytona_api_key"),
    SecretKey.MCP_OAUTH_CLIENT_SECRET: ("mcp", "oauth_client_secret"),
    SecretKey.COMPOSIO_API_KEY: (None, "composio_api_key"),
    SecretKey.COMPOSIO_ENCRYPTION_KEY: (None, "composio_encryption_key"),
    SecretKey.COMPOSIO_WEBHOOK_SECRET: (None, "composio_webhook_secret"),
    SecretKey.JWT_SECRET_KEY: (None, "jwt_secret_key"),
    # ENCRYPTION_KEY is not directly mapped - extend if needed
}


def load_secrets(provider: SecretProvider) -> dict[SecretKey, str]:
    """Fetch all mapped secrets from the provider.

    Args:
        provider: The secret provider to fetch from

    Returns:
        Dict of secret keys to their values (only includes found secrets)
    """
    secrets = provider.get_secrets(ALL_SECRETS)
    logger.info("Loaded %d/%d secrets from provider", len(secrets), len(ALL_SECRETS))
    return secrets
