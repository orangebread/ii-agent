"""Custom Pydantic settings source for GCP Secret Manager.

This module provides a PydanticBaseSettingsSource that loads secrets from
GCP Secret Manager during Settings construction. This eliminates the need
for post-construction mutation via apply_secrets().

Priority order in settings_customise_sources:
    init_settings > env_settings > gcp_secrets > dotenv_settings

Usage:
    The source is automatically included when GCP_PROJECT_ID is set as an
    environment variable. No manual loading or lifespan hooks needed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Tuple

from pydantic_settings import PydanticBaseSettingsSource

logger = logging.getLogger(__name__)

# Mapping from SecretKey enum name to (nested_attr, field_name).
# Duplicated from loader.py to avoid circular imports at class definition time.
# Format: secret_key_name -> (nested_section, field_name) or (None, field_name) for top-level.
_SECRET_FIELD_MAP: dict[str, tuple[str | None, str]] = {
    "DATABASE_URL": ("database", "url"),
    "REDIS_SESSION_URL": ("redis", "session_url"),
    "GOOGLE_CLIENT_SECRET": ("oauth", "google_client_secret"),
    "GITHUB_CLIENT_SECRET": ("oauth", "github_client_secret"),
    "REVENUECAT_CLIENT_SECRET": ("oauth", "revenuecat_client_secret"),
    "GITHUB_APP_PRIVATE_KEY": ("oauth", "github_app_private_key"),
    "SESSION_SECRET_KEY": ("oauth", "session_secret_key"),
    "STRIPE_SECRET_KEY": ("stripe", "secret_key"),
    "STRIPE_WEBHOOK_SECRET": ("stripe", "webhook_secret"),
    "SANDBOX_E2B_API_KEY": ("sandbox", "e2b_api_key"),
    "SANDBOX_DAYTONA_API_KEY": ("sandbox", "daytona_api_key"),
    "MCP_OAUTH_CLIENT_SECRET": ("mcp", "oauth_client_secret"),
    "COMPOSIO_API_KEY": (None, "composio_api_key"),
    "COMPOSIO_ENCRYPTION_KEY": (None, "composio_encryption_key"),
    "COMPOSIO_WEBHOOK_SECRET": (None, "composio_webhook_secret"),
    "JWT_SECRET_KEY": (None, "jwt_secret_key"),
}


class GCPSecretManagerSource(PydanticBaseSettingsSource):
    """Pydantic settings source that reads from GCP Secret Manager.

    Bootstrap values (GCP_PROJECT_ID, GCP_SECRET_PREFIX) are read directly
    from os.environ since Settings hasn't been constructed yet when this
    source runs.

    If GCP_PROJECT_ID is not set, this source returns an empty dict (no-op).
    """

    def __init__(self, settings_cls: type[Any]) -> None:
        super().__init__(settings_cls)
        self._project_id = os.environ.get("GCP_PROJECT_ID")
        self._prefix = os.environ.get("GCP_SECRET_PREFIX", "ii-agent")
        self._secrets: dict[str, str] | None = None

    def _load_secrets(self) -> dict[str, str]:
        """Fetch all mapped secrets from GCP Secret Manager.

        Returns a dict of secret_key_name -> value for secrets that were found.
        Results are cached for the lifetime of this source instance.
        """
        if self._secrets is not None:
            return self._secrets

        if not self._project_id:
            self._secrets = {}
            return self._secrets

        try:
            from ii_agent.core.secrets.provider import GCPSecretProvider
            from ii_agent.core.secrets.keys import ALL_SECRETS

            provider = GCPSecretProvider(
                project_id=self._project_id,
                prefix=self._prefix,
            )
            raw_secrets = provider.get_secrets(ALL_SECRETS)
            self._secrets = {key.name: value for key, value in raw_secrets.items()}
            logger.info(
                "GCP Secret Manager: loaded %d/%d secrets",
                len(self._secrets),
                len(ALL_SECRETS),
            )
        except ImportError:
            logger.warning(
                "google-cloud-secret-manager not installed, skipping GCP secrets. "
                "Install with: pip install google-cloud-secret-manager>=2.20.0"
            )
            self._secrets = {}
        except Exception as e:
            logger.error("Failed to load GCP secrets: %s", e, exc_info=True)
            self._secrets = {}

        return self._secrets

    def get_field_value(self, field: Any, field_name: str) -> Tuple[Any, str, bool]:
        """Get the value for a single field.

        This method is called by PydanticBaseSettingsSource for each field.
        We return (None, field_name, False) since we provide all values
        via __call__() instead.
        """
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return a nested dict of settings values from GCP secrets.

        The returned dict structure matches the Settings model layout:
        - Top-level fields: {"composio_api_key": "value"}
        - Nested fields: {"database": {"url": "value"}}
        """
        secrets = self._load_secrets()
        if not secrets:
            return {}

        result: dict[str, Any] = {}

        for secret_name, value in secrets.items():
            mapping = _SECRET_FIELD_MAP.get(secret_name)
            if mapping is None:
                logger.debug("No settings mapping for secret %s, skipping", secret_name)
                continue

            nested_attr, field_name = mapping
            if nested_attr is not None:
                result.setdefault(nested_attr, {})[field_name] = value
            else:
                result[field_name] = value

        logger.info("GCP Secret Manager: mapped %d secret values to settings fields", len(secrets))
        return result
