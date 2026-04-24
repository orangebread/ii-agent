"""Sandbox domain enums."""

from enum import StrEnum


class SandboxStatus(StrEnum):
    """Sandbox lifecycle status values."""

    NOT_INITIALIZED = "not_initialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    DELETED = "deleted"
    ERROR = "error"


class SandboxProviderType(StrEnum):
    """Supported sandbox provider backends."""

    E2B = "e2b"
    DOCKER = "docker"
    DAYTONA = "daytona"
