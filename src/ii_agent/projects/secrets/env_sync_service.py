"""Sandbox environment file synchronization for project secrets."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.exceptions import ValidationError
from ii_agent.core.logger import logger
from ii_agent.projects.secrets.utils import is_valid_env_var_name

if TYPE_CHECKING:
    from ii_agent.agents.sandboxes.service import SandboxService

_DOTENV_BLOCK_START = "# >>> ii-agent managed secrets >>>"
_DOTENV_BLOCK_END = "# <<< ii-agent managed secrets <<<"
_SHELL_BLOCK_START = "# >>> ii-agent managed exports >>>"
_SHELL_BLOCK_END = "# <<< ii-agent managed exports <<<"
_USER_ENV_PATH = "/app/.user_env.sh"
_WORKSPACE_ROOT = "/workspace"
_SYNC_METADATA_KEY = "ii_agent_secret_sync"


@dataclass(frozen=True)
class SandboxEnvTargetState:
    """Normalized env materialization target for a sandbox session."""

    env_values: dict[str, str]
    normalized_project_path: str | None
    revision: str


@dataclass(frozen=True)
class SandboxEnvSyncResult:
    """Result of syncing persisted secrets into sandbox runtime files."""

    runtime_synced: bool
    restart_required: bool = False


class SandboxEnvSyncService:
    """Synchronize persisted project secrets into sandbox env files."""

    def __init__(self, *, sandbox_service: SandboxService) -> None:
        self._sandbox_service = sandbox_service

    async def sync_env_files(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        secrets: dict[str, Any],
        project_path: str | None,
        database_url: str | None,
        provision_if_missing: bool = True,
        sandbox: Any | None = None,
    ) -> SandboxEnvSyncResult:
        """Write the current managed secret set into sandbox env files.

        The database remains the source of truth for secret values. This service only
        materializes the latest view into runtime files through the session sandbox.
        """
        target_state = self.build_target_state(
            secrets=secrets,
            project_path=project_path,
            database_url=database_url,
        )

        if sandbox is None:
            if provision_if_missing:
                sandbox = await self._sandbox_service.get_sandbox_by_session(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                )
            else:
                sandbox = await self._sandbox_service.get_sandbox_for_session(
                    db,
                    session_id=session_id,
                )
                if sandbox is None:
                    return SandboxEnvSyncResult(runtime_synced=False)

        sandbox_id = uuid.UUID(str(sandbox.sandbox_id))
        provider_data = await self._sandbox_service.load_provider_data(sandbox_id, db=db)
        if self.is_sync_metadata_current(provider_data, target_state):
            return SandboxEnvSyncResult(runtime_synced=True)

        restart_required = self._has_active_terminal_sessions(provider_data)

        await self.apply_target_state(
            sandbox=sandbox,
            target_state=target_state,
            previous_project_path=self.get_synced_project_path(provider_data),
        )

        updated_provider_data = self.attach_sync_metadata(provider_data, target_state)
        await self._sandbox_service.persist_provider_data(
            sandbox_id,
            updated_provider_data,
            db=db,
        )
        return SandboxEnvSyncResult(
            runtime_synced=True,
            restart_required=restart_required,
        )

    @classmethod
    def build_target_state(
        cls,
        *,
        secrets: dict[str, Any],
        project_path: str | None,
        database_url: str | None,
    ) -> SandboxEnvTargetState:
        normalized_project_path = cls._normalize_project_path(project_path)
        env_values = cls._build_env_values(secrets=secrets, database_url=database_url)
        return SandboxEnvTargetState(
            env_values=env_values,
            normalized_project_path=normalized_project_path,
            revision=cls._compute_revision(
                env_values=env_values,
                project_path=normalized_project_path,
            ),
        )

    @staticmethod
    def _build_env_values(
        *,
        secrets: dict[str, Any],
        database_url: str | None,
    ) -> dict[str, str]:
        env_values: dict[str, str] = {}
        for key, value in secrets.items():
            if not isinstance(key, str) or not key:
                continue
            if not is_valid_env_var_name(key):
                logger.warning("Skipping invalid environment variable name during sync: %r", key)
                continue
            if value is None:
                continue
            env_values[key] = str(value)

        if database_url:
            env_values["DATABASE_URL"] = database_url
        elif "DATABASE_URL" in env_values and not env_values["DATABASE_URL"]:
            env_values.pop("DATABASE_URL", None)

        return {key: env_values[key] for key in sorted(env_values)}

    @staticmethod
    def _compute_revision(*, env_values: dict[str, str], project_path: str | None) -> str:
        payload = json.dumps(
            {
                "env_values": env_values,
                "project_path": project_path,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_project_path(project_path: str | None) -> str | None:
        if not isinstance(project_path, str) or not project_path.strip():
            return None

        raw_path = project_path.strip()
        if raw_path.startswith("./"):
            raw_path = raw_path[2:]

        if posixpath.isabs(raw_path):
            normalized = posixpath.normpath(raw_path)
        else:
            normalized = posixpath.normpath(posixpath.join(_WORKSPACE_ROOT, raw_path))

        if normalized != _WORKSPACE_ROOT and not normalized.startswith(f"{_WORKSPACE_ROOT}/"):
            raise ValidationError("Project path must stay within the sandbox workspace")

        return normalized

    @classmethod
    def get_sync_metadata(cls, provider_data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(provider_data, dict):
            return {}
        metadata = provider_data.get(_SYNC_METADATA_KEY)
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def get_synced_project_path(cls, provider_data: dict[str, Any] | None) -> str | None:
        project_path = cls.get_sync_metadata(provider_data).get("project_path")
        return project_path if isinstance(project_path, str) else None

    @classmethod
    def is_sync_metadata_current(
        cls,
        provider_data: dict[str, Any] | None,
        target_state: SandboxEnvTargetState,
    ) -> bool:
        metadata = cls.get_sync_metadata(provider_data)
        return (
            metadata.get("revision") == target_state.revision
            and metadata.get("project_path") == target_state.normalized_project_path
        )

    @classmethod
    def attach_sync_metadata(
        cls,
        provider_data: dict[str, Any] | None,
        target_state: SandboxEnvTargetState,
    ) -> dict[str, Any]:
        merged = dict(provider_data or {})
        merged[_SYNC_METADATA_KEY] = {
            "revision": target_state.revision,
            "project_path": target_state.normalized_project_path,
        }
        return merged

    @staticmethod
    def _has_active_terminal_sessions(provider_data: dict[str, Any] | None) -> bool:
        pty_sessions = (provider_data or {}).get("pty_sessions")
        return isinstance(pty_sessions, dict) and bool(pty_sessions)

    @classmethod
    async def apply_target_state(
        cls,
        *,
        sandbox: Any,
        target_state: SandboxEnvTargetState,
        previous_project_path: str | None = None,
    ) -> None:
        await cls._sync_shell_exports(sandbox=sandbox, env_values=target_state.env_values)

        if previous_project_path and previous_project_path != target_state.normalized_project_path:
            await cls._clear_project_dotenv_if_present(
                sandbox=sandbox,
                project_path=previous_project_path,
            )

        if target_state.normalized_project_path is None:
            return

        if target_state.env_values:
            await sandbox.create_directory(target_state.normalized_project_path, exist_ok=True)
            await cls._sync_project_dotenv(
                sandbox=sandbox,
                project_path=target_state.normalized_project_path,
                env_values=target_state.env_values,
            )
            return

        await cls._clear_project_dotenv_if_present(
            sandbox=sandbox,
            project_path=target_state.normalized_project_path,
        )

    @classmethod
    async def _sync_project_dotenv(
        cls,
        *,
        sandbox: Any,
        project_path: str,
        env_values: dict[str, str],
    ) -> None:
        dotenv_path = posixpath.join(project_path, ".env")
        existing = await cls._read_optional_file(sandbox=sandbox, file_path=dotenv_path)
        managed_block = cls._render_dotenv_block(env_values)
        updated = cls._replace_managed_block(
            existing_content=existing,
            managed_block=managed_block,
            start_marker=_DOTENV_BLOCK_START,
            end_marker=_DOTENV_BLOCK_END,
        )
        await sandbox.write_file(dotenv_path, updated)

    @classmethod
    async def _clear_project_dotenv_if_present(
        cls,
        *,
        sandbox: Any,
        project_path: str,
    ) -> None:
        dotenv_path = posixpath.join(project_path, ".env")
        if not await sandbox.file_exists(dotenv_path):
            return
        await cls._sync_project_dotenv(
            sandbox=sandbox,
            project_path=project_path,
            env_values={},
        )

    @classmethod
    async def _sync_shell_exports(
        cls,
        *,
        sandbox: Any,
        env_values: dict[str, str],
    ) -> None:
        existing = await cls._read_optional_file(sandbox=sandbox, file_path=_USER_ENV_PATH)
        managed_block = cls._render_shell_block(env_values)
        updated = cls._replace_managed_block(
            existing_content=existing,
            managed_block=managed_block,
            start_marker=_SHELL_BLOCK_START,
            end_marker=_SHELL_BLOCK_END,
        )
        await sandbox.write_file(_USER_ENV_PATH, updated)

    @staticmethod
    async def _read_optional_file(*, sandbox: Any, file_path: str) -> str:
        if not await sandbox.file_exists(file_path):
            return ""
        content = await sandbox.read_file(file_path)
        return content if isinstance(content, str) else str(content)

    @staticmethod
    def _render_dotenv_block(env_values: dict[str, str]) -> str:
        if not env_values:
            return ""
        return "\n".join(
            f"{key}={SandboxEnvSyncService._format_dotenv_value(value)}"
            for key, value in env_values.items()
        )

    @staticmethod
    def _render_shell_block(env_values: dict[str, str]) -> str:
        if not env_values:
            return ""
        return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in env_values.items())

    @staticmethod
    def _format_dotenv_value(value: str) -> str:
        if not value:
            return '""'

        if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", value):
            return value

        return json.dumps(value)

    @staticmethod
    def _replace_managed_block(
        *,
        existing_content: str,
        managed_block: str,
        start_marker: str,
        end_marker: str,
    ) -> str:
        rendered_block = f"{start_marker}\n{managed_block}\n{end_marker}" if managed_block else ""

        start_index = existing_content.find(start_marker)
        end_index = existing_content.find(end_marker, start_index) if start_index != -1 else -1

        if start_index != -1 and end_index != -1:
            prefix = existing_content[:start_index].rstrip("\n")
            suffix = existing_content[end_index + len(end_marker) :].lstrip("\n")
            parts = [part for part in (prefix, rendered_block, suffix) if part]
            updated = "\n\n".join(parts)
        elif rendered_block:
            base = existing_content.rstrip("\n")
            updated = f"{base}\n\n{rendered_block}" if base else rendered_block
        else:
            updated = existing_content.strip("\n")

        return f"{updated}\n" if updated else ""
