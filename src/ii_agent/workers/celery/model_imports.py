"""Celery ORM model bootstrap.

Imports all SQLAlchemy model modules so string-based relationships resolve
reliably in Celery worker processes.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module

from sqlalchemy.orm import configure_mappers


MODEL_MODULES: tuple[str, ...] = (
    "ii_agent.users.models",
    "ii_agent.billing.models",
    "ii_agent.chat.messages.models",
    "ii_agent.chat.providers.models",
    "ii_agent.content.media.models",
    "ii_agent.settings.skills.models",
    "ii_agent.content.slides.models",
    "ii_agent.content.storybook.models",
    "ii_agent.tasks.models",
    "ii_agent.agents.runs.models",
    "ii_agent.files.models",
    "ii_agent.integrations.connectors.models",
    "ii_agent.projects.models",
    "ii_agent.projects.databases.models",
    "ii_agent.projects.deployments.models",
    "ii_agent.projects.subdomains.models",
    "ii_agent.realtime.events.models",
    "ii_agent.sessions.models",
    "ii_agent.sessions.wishlist.models",
    "ii_agent.sessions.pin.models",
    "ii_agent.settings.llm.models",
    "ii_agent.settings.provider_connections.models",
    "ii_agent.settings.mcp.models",
    "ii_agent.agents.sandboxes.models",
)


@lru_cache(maxsize=1)
def import_model_modules() -> None:
    """Import all ORM model modules and eagerly configure SQLAlchemy mappers."""
    for module_path in MODEL_MODULES:
        import_module(module_path)
    configure_mappers()
