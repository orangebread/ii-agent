"""HTTP middleware and exception handler registration."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from ii_agent.core.config.settings import Settings
from ii_agent.core.exceptions import IIAgentError
from ii_agent.core.middleware import (
    exception_logging_middleware,
    ii_agent_error_handler,
    request_tracing_middleware,
    setup_cors,
)


def _build_allowed_origins(settings: Settings) -> list[str]:
    origins = {"http://localhost:1420", "http://localhost:3000"}

    parsed_frontend_url = urlparse(settings.ii_frontend_url)
    if parsed_frontend_url.scheme and parsed_frontend_url.netloc:
        origins.add(f"{parsed_frontend_url.scheme}://{parsed_frontend_url.netloc}")

    return sorted(origins)


def configure_middleware(app: FastAPI, settings: Settings) -> None:
    """Register middleware in the same order as the legacy bootstrap."""
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oauth.session_secret_key,
        same_site="lax",
        https_only=False,
    )

    app.middleware("http")(request_tracing_middleware)
    app.middleware("http")(exception_logging_middleware)

    app.exception_handler(IIAgentError)(ii_agent_error_handler)
    app.add_middleware(GZipMiddleware)

    # Register CORS last so it wraps exception-generated responses too.
    setup_cors(app, allowed_origins=_build_allowed_origins(settings))
