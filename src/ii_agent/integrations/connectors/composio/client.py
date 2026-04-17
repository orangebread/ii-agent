"""Composio SDK client singleton."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Optional

from composio import Composio
from dotenv import dotenv_values

from ii_agent.core.config.settings import get_settings
from ii_agent.core.logger import logger


class ComposioClient:
    """Singleton wrapper around Composio SDK client."""

    _instance: Optional[Composio] = None
    _api_key_digest: Optional[str] = None
    _api_key_masked: Optional[str] = None
    _api_key_source: Optional[str] = None
    _base_url: Optional[str] = None

    @staticmethod
    def _mask_secret(secret: str) -> str:
        if len(secret) <= 10:
            return "*" * len(secret)
        return f"{secret[:8]}*****{secret[-4:]}"

    @staticmethod
    def _fingerprint_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _get_dotenv_value(key: str) -> Optional[str]:
        env_file = Path(".env")
        if not env_file.exists():
            return None
        return dotenv_values(env_file).get(key)

    @classmethod
    def _resolve_client_context(cls, api_key: Optional[str]) -> dict[str, Any]:
        settings = get_settings()
        effective_key = api_key or settings.composio_api_key
        if not effective_key:
            raise ValueError(
                "COMPOSIO_API_KEY not configured. Set COMPOSIO_API_KEY environment variable."
            )

        env_key = os.environ.get("COMPOSIO_API_KEY")
        dotenv_key = cls._get_dotenv_value("COMPOSIO_API_KEY")
        base_url = os.environ.get("COMPOSIO_BASE_URL") or "https://backend.composio.dev"

        if api_key is not None:
            api_key_source = "override"
        elif env_key:
            api_key_source = "env"
        elif dotenv_key:
            api_key_source = "dotenv"
        else:
            api_key_source = "settings"

        return {
            "settings": settings,
            "effective_key": effective_key,
            "api_key_source": api_key_source,
            "api_key_masked": cls._mask_secret(effective_key),
            "api_key_digest": cls._fingerprint_secret(effective_key),
            "base_url": base_url,
            "base_url_source": "env" if os.environ.get("COMPOSIO_BASE_URL") else "default",
        }

    @classmethod
    def _log_initialization(cls, context: dict[str, Any]) -> None:
        logger.bind(
            composio_api_key_source=context["api_key_source"],
            composio_api_key_masked=context["api_key_masked"],
            composio_api_key_fingerprint=context["api_key_digest"],
            composio_base_url=context["base_url"],
            composio_base_url_source=context["base_url_source"],
            app_environment=context["settings"].environment,
        ).info("Initializing Composio client")

    @classmethod
    def _warn_on_cached_key_mismatch(cls, context: dict[str, Any]) -> None:
        if cls._api_key_digest is None or context["api_key_digest"] == cls._api_key_digest:
            return

        logger.bind(
            requested_composio_api_key_source=context["api_key_source"],
            requested_composio_api_key_masked=context["api_key_masked"],
            requested_composio_api_key_fingerprint=context["api_key_digest"],
            cached_composio_api_key_source=cls._api_key_source,
            cached_composio_api_key_masked=cls._api_key_masked,
            cached_composio_api_key_fingerprint=cls._api_key_digest,
            composio_base_url=cls._base_url,
        ).warning(
            "Composio client already initialized with a different API key; "
            "reusing cached singleton. Restart the process or call ComposioClient.reset() "
            "to pick up the new key."
        )

    @classmethod
    def get_client(cls, api_key: Optional[str] = None) -> Composio:
        """Get or create Composio client instance.

        Args:
            api_key: Optional API key override. If not provided, uses config.composio_api_key

        Returns:
            Composio: The Composio SDK client instance

        Raises:
            ValueError: If COMPOSIO_API_KEY is not configured
        """
        context = cls._resolve_client_context(api_key)

        if cls._instance is None:
            cls._log_initialization(context)
            cls._instance = Composio(api_key=context["effective_key"])
            cls._api_key_digest = context["api_key_digest"]
            cls._api_key_masked = context["api_key_masked"]
            cls._api_key_source = context["api_key_source"]
            cls._base_url = context["base_url"]
        else:
            cls._warn_on_cached_key_mismatch(context)

        return cls._instance

    @classmethod
    def reset(cls):
        """Reset client instance (for testing)."""
        cls._instance = None
        cls._api_key_digest = None
        cls._api_key_masked = None
        cls._api_key_source = None
        cls._base_url = None
