"""Daytona sandbox provider implementation.

The official Daytona Python SDK currently requires ``websockets>=15,<16``,
which conflicts with the existing ii-agent dependency graph. This provider
uses Daytona's HTTP and toolbox endpoints directly through the repo's existing
``httpx`` and ``websockets`` dependencies.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import math
import os
import posixpath
import shlex
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import IO, Any, AsyncIterator, Dict, List, Literal, Optional
from urllib.parse import urljoin, urlparse

from fastmcp import Client
import httpx
import websockets

from ii_agent.agents.sandboxes.base import Sandbox
from ii_agent.agents.sandboxes.exceptions import (
    SandboxAuthenticationError,
    SandboxCreationError,
    SandboxNotFoundException,
    SandboxNotInitializedError,
    SandboxOperationError,
    SandboxTimeoutException,
)
from ii_agent.agents.sandboxes.schemas import (
    EXCLUDED_DIRS,
    INLINE_CONTENT_MAX_SIZE,
    INLINE_CONTENT_PREFETCH_DEPTH,
    INLINE_CONTENT_TOTAL_MAX,
    MAX_FILE_CONTENT_SIZE,
    FileContentResponse,
    FileTreeNode,
    FileUpload,
    SandboxFileInfo,
    SandboxInfo,
    detect_language,
    guess_mime_type,
    is_binary_file_path,
    is_image_file_path,
)
from ii_agent.agents.sandboxes.terminal import (
    LiveTerminalHandle,
    LiveTerminalNotFoundError,
    TerminalDataCallback,
)
from ii_agent.agents.sandboxes.types import SandboxProviderType, SandboxStatus
from ii_agent.core.config.settings import Settings, get_settings
from ii_agent.core.logger import logger


_STARTED_STATES = {"started"}
_PENDING_STATES = {
    "creating",
    "restoring",
    "starting",
    "pending_build",
    "building_snapshot",
    "pulling_snapshot",
}
_PAUSED_STATES = {"stopped", "stopping", "archived", "archiving"}
_DELETED_STATES = {"destroyed", "destroying"}
_ERROR_STATES = {"error", "build_failed", "unknown"}


@dataclass(slots=True)
class _DaytonaFileInfo:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    mod_time: str | None = None


@dataclass(slots=True)
class _DaytonaWatchEvent:
    type: str
    name: str
    path: str


def _coerce_content(content: str | bytes | IO) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raw = content.read()
    return raw.encode("utf-8") if isinstance(raw, str) else raw


def _field(payload: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return default


def _json_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return "" if value is None else str(value)
    return json.dumps(value, sort_keys=True)


def _sanitize_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:63] or f"ii-agent-{uuid.uuid4().hex[:12]}"


def _state_value(raw_state: Any) -> str:
    if raw_state is None:
        return ""
    if isinstance(raw_state, str):
        return raw_state.lower()
    return str(getattr(raw_state, "value", raw_state)).lower()


class DaytonaLiveTerminalHandle(LiveTerminalHandle):
    """Provider-agnostic wrapper around a Daytona toolbox PTY session."""

    def __init__(
        self,
        *,
        session_id: str,
        websocket: Any,
        reader_task: asyncio.Task[None],
        resize_callback: Any,
        kill_callback: Any,
    ) -> None:
        self._session_id = session_id
        self._websocket = websocket
        self._reader_task = reader_task
        self._resize_callback = resize_callback
        self._kill_callback = kill_callback
        self._exit_code: int | None = None
        self._error: str | None = None

    @property
    def pid(self) -> int:
        return zlib.crc32(self._session_id.encode("utf-8"))

    def set_result(self, *, exit_code: int | None = None, error: str | None = None) -> None:
        if exit_code is not None:
            self._exit_code = exit_code
        if error is not None:
            self._error = error

    async def send_input(self, data: bytes) -> None:
        try:
            await self._websocket.send(data)
        except Exception as exc:
            raise LiveTerminalNotFoundError(
                f"Daytona PTY session {self._session_id} is not connected"
            ) from exc

    async def resize(self, cols: int, rows: int) -> None:
        await self._resize_callback(cols=cols, rows=rows)

    async def kill(self) -> bool:
        await self._kill_callback()
        return True

    async def disconnect(self) -> None:
        if not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        await self._websocket.close()

    async def wait(self) -> int | None:
        await self._reader_task
        if self._error:
            raise LiveTerminalNotFoundError(
                f"Daytona PTY session {self._session_id} failed: {self._error}"
            )
        return self._exit_code


class _PollingWatchHandle:
    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task

    async def stop(self) -> None:
        if self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


class DaytonaSandbox(Sandbox):
    """Daytona-backed sandbox provider."""

    PROVIDER: SandboxProviderType = SandboxProviderType.DAYTONA

    def __init__(
        self,
        sandbox_id: str,
        session_id: str,
        provider_sandbox_id: str,
        *,
        status: SandboxStatus = SandboxStatus.NOT_INITIALIZED,
        metadata: Optional[Dict[str, Any]] = None,
        sandbox: Optional[dict[str, Any]] = None,
        expired_at: Optional[datetime] = None,
        config: Optional[Settings] = None,
    ) -> None:
        super().__init__(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id=provider_sandbox_id,
            status=status,
            metadata=metadata,
            expired_at=expired_at,
        )
        self.sandbox = sandbox
        self._config = config or get_settings()
        self.mcp_client: Optional[Client] = None

    def get_provider_id(self) -> str:
        return self.provider_sandbox_id

    @property
    def upload_path(self) -> str:
        return self._config.workspace_upload_path

    async def get_info(self) -> SandboxInfo:
        vscode_url = None
        if self.status == SandboxStatus.RUNNING:
            try:
                vscode_url = await self.expose_port(self._config.vscode_port)
            except Exception:
                pass
        return SandboxInfo(
            id=self.sandbox_id,
            session_id=self.session_id,
            status=await self.get_status(),
            expired_at=self.expired_at,
            provider=SandboxProviderType.DAYTONA,
            vscode_url=vscode_url,
        )

    async def get_status(self) -> SandboxStatus:
        sandbox = await self._get_remote_sandbox()
        self.sandbox = sandbox
        self.status = self._to_sandbox_status(_field(sandbox, "state"))
        return self.status

    @classmethod
    async def create(
        cls,
        sandbox_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "DaytonaSandbox":
        cfg = get_settings()
        sandbox_metadata = cls._build_metadata(cfg, sandbox_id, session_id, metadata)
        expired_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.sandbox.timeout_seconds)
        instance = cls(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id="pending",
            metadata=sandbox_metadata,
            expired_at=expired_at,
            config=cfg,
        )
        try:
            sandbox = await instance._api_request(
                "POST",
                "/sandbox",
                json=cls._build_create_payload(cfg, sandbox_id, sandbox_metadata),
                timeout=cfg.sandbox.timeout_seconds,
            )
        except SandboxOperationError as exc:
            raise SandboxCreationError(str(exc)) from exc

        provider_sandbox_id = str(_field(sandbox, "id", "sandboxId", "sandbox_id"))
        if not provider_sandbox_id or provider_sandbox_id == "None":
            raise SandboxCreationError(
                f"Daytona create response did not include sandbox id: {sandbox}"
            )

        instance.provider_sandbox_id = provider_sandbox_id
        instance.sandbox = sandbox
        await instance._wait_for_started(timeout=cfg.sandbox.timeout_seconds)
        instance.status = SandboxStatus.RUNNING
        logger.info("Created Daytona sandbox %s (provider: %s)", sandbox_id, provider_sandbox_id)
        return instance

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        session_id: str,
        provider_sandbox_id: str,
    ) -> "DaytonaSandbox":
        cfg = get_settings()
        instance = cls(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id=provider_sandbox_id,
            metadata={"provider": "daytona"},
            config=cfg,
        )
        sandbox = await instance._get_remote_sandbox()
        instance.sandbox = sandbox
        status = instance._to_sandbox_status(_field(sandbox, "state"))
        if status == SandboxStatus.PAUSED:
            await instance._api_request("POST", f"/sandbox/{provider_sandbox_id}/start")
            await instance._wait_for_started(timeout=cfg.sandbox.timeout_seconds)
            status = SandboxStatus.RUNNING
        instance.status = status
        instance.metadata.update(instance._metadata_from_sandbox(sandbox))
        instance.expired_at = datetime.now(timezone.utc) + timedelta(
            seconds=cfg.sandbox.timeout_seconds
        )
        return instance

    async def pause(self) -> None:
        status = await self.get_status()
        if status == SandboxStatus.PAUSED:
            return
        if status in {SandboxStatus.DELETED, SandboxStatus.ERROR}:
            raise SandboxNotFoundException(self.provider_sandbox_id)
        await self._api_request(
            "POST",
            f"/sandbox/{self.provider_sandbox_id}/stop",
            params={"force": False},
        )
        self.status = SandboxStatus.PAUSED

    async def set_timeout(self, timeout_seconds: int) -> None:
        await self._ensure_sandbox_connection()
        minutes = max(1, math.ceil(timeout_seconds / 60))
        await self._api_request("POST", f"/sandbox/{self.provider_sandbox_id}/autostop/{minutes}")
        self.expired_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)

    async def run_command(
        self,
        command: str,
        background: bool = False,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> str:
        await self._ensure_sandbox_connection()
        if background:
            command = f"nohup bash -lc {shlex.quote(command)} >/tmp/ii-agent-daytona-bg.log 2>&1 & echo $!"
        payload: dict[str, Any] = {"command": command}
        if cwd:
            payload["cwd"] = cwd
        if timeout:
            payload["timeout"] = timeout
        response = await self._toolbox_request(
            "POST",
            "/process/execute",
            json=payload,
            timeout=(timeout + 5) if timeout else None,
        )
        exit_code = _field(response, "exitCode", "exit_code", "code", default=0)
        result = str(_field(response, "result", default="") or "")
        if exit_code not in (0, None):
            raise SandboxOperationError(
                "run_command",
                f"Command failed with exit code {exit_code}: {result}",
            )
        return result

    async def run_python_code(self, code: str) -> str:
        return await self.run_command(f"python3 -c {shlex.quote(code)}", timeout=120)

    async def create_live_terminal(
        self,
        *,
        cols: int,
        rows: int,
        cwd: str,
        on_data: TerminalDataCallback,
        envs: dict[str, str] | None = None,
        timeout: float | None = 0,
    ) -> LiveTerminalHandle:
        await self._ensure_sandbox_connection()
        session_id = f"ii-agent-{uuid.uuid4().hex}"
        response = await self._toolbox_request(
            "POST",
            "/process/pty",
            json={
                "id": session_id,
                "cwd": cwd,
                "envs": envs,
                "cols": cols,
                "rows": rows,
                "lazyStart": True,
            },
        )
        session_id = str(_field(response, "sessionId", "session_id", default=session_id))
        ws_url = self._toolbox_url(f"/process/pty/{session_id}/connect")
        ws_url = ws_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        websocket = await websockets.connect(ws_url, extra_headers=self._headers())
        connected = asyncio.Event()
        handle_ref: dict[str, DaytonaLiveTerminalHandle] = {}

        async def _reader() -> None:
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            control = json.loads(message)
                        except json.JSONDecodeError:
                            await self._call_terminal_callback(on_data, message.encode("utf-8"))
                            continue
                        if control.get("type") == "control":
                            status = control.get("status")
                            if status == "connected":
                                connected.set()
                            elif status == "error":
                                if handle := handle_ref.get("handle"):
                                    handle.set_result(
                                        error=str(control.get("error", "unknown error"))
                                    )
                                connected.set()
                            continue
                        await self._call_terminal_callback(on_data, message.encode("utf-8"))
                    else:
                        await self._call_terminal_callback(on_data, message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if handle := handle_ref.get("handle"):
                    handle.set_result(error=str(exc))
                connected.set()
            finally:
                if handle := handle_ref.get("handle"):
                    handle.set_result(
                        exit_code=handle._exit_code if handle._exit_code is not None else 0
                    )

        async def _resize(*, cols: int, rows: int) -> None:
            await self._toolbox_request(
                "POST",
                f"/process/pty/{session_id}/resize",
                json={"cols": cols, "rows": rows},
            )

        async def _kill() -> None:
            await self._toolbox_request("DELETE", f"/process/pty/{session_id}")

        reader_task = asyncio.create_task(_reader())
        handle = DaytonaLiveTerminalHandle(
            session_id=session_id,
            websocket=websocket,
            reader_task=reader_task,
            resize_callback=_resize,
            kill_callback=_kill,
        )
        handle_ref["handle"] = handle
        wait_timeout = 10 if timeout is None or timeout == 0 else timeout
        await asyncio.wait_for(connected.wait(), timeout=wait_timeout)
        if handle._error:
            raise LiveTerminalNotFoundError(
                f"Daytona PTY session {session_id} failed: {handle._error}"
            )
        return handle

    async def read_file(self, file_path: str) -> str:
        content = await self.download_file(file_path, format="text")
        return "" if content is None else str(content)

    async def write_file(
        self,
        file_path: str,
        content: str | bytes | IO,
    ) -> SandboxFileInfo:
        await self._write_bytes(file_path, _coerce_content(content))
        return SandboxFileInfo(name=os.path.basename(file_path), path=file_path, type="file")

    async def write_files(self, files: List[FileUpload]) -> List[SandboxFileInfo]:
        return [await self.write_file(file.path, file.content) for file in files]

    async def upload_file(
        self,
        file_content: str | bytes | IO,
        remote_file_path: str,
    ) -> bool:
        await self._write_bytes(remote_file_path, _coerce_content(file_content))
        return True

    async def download_file(
        self,
        remote_file_path: str,
        format: Literal["text", "bytes"] = "text",
    ) -> Optional[str | bytes]:
        await self._ensure_sandbox_connection()
        output = await self.run_command(
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "import base64\n"
            f"data = Path({remote_file_path!r}).read_bytes()\n"
            "print(base64.b64encode(data).decode('ascii'))\n"
            "PY",
            timeout=120,
        )
        raw = base64.b64decode(output.strip())
        if format == "bytes":
            return raw
        return raw.decode("utf-8", errors="replace")

    async def download_file_stream(
        self,
        remote_file_path: str,
    ) -> AsyncIterator[bytes]:
        content = await self.download_file(remote_file_path, format="bytes")

        async def _generator() -> AsyncIterator[bytes]:
            if isinstance(content, bytes):
                yield content

        return _generator()

    async def delete_file(self, file_path: str) -> bool:
        await self.run_command(f"rm -rf {shlex.quote(file_path)}")
        return True

    async def create_directory(
        self,
        directory_path: str,
        exist_ok: bool = False,
    ) -> bool:
        exists = await self.file_exists(directory_path)
        if exists and not exist_ok:
            raise SandboxOperationError(
                "create_directory",
                f"Directory {directory_path} already exists",
            )
        await self.run_command(f"mkdir -p {shlex.quote(directory_path)}")
        return True

    async def file_exists(self, file_path: str) -> bool:
        try:
            await self._get_file_info(file_path)
            return True
        except SandboxOperationError as exc:
            if "404" in str(exc) or "not found" in str(exc).lower():
                return False
            raise

    async def list_files_with_contents(
        self,
        path: str,
        max_depth: int = 10,
        inline_content_max_depth: int | None = None,
    ) -> tuple[FileTreeNode, dict[str, dict[str, str]]]:
        inline_depth = (
            INLINE_CONTENT_PREFETCH_DEPTH
            if inline_content_max_depth is None
            else inline_content_max_depth
        )
        contents: dict[str, dict[str, str]] = {}
        total_bytes = 0

        async def _collect(node: FileTreeNode, *, current_depth: int) -> None:
            nonlocal total_bytes
            if node.type == "directory" and node.children:
                for child in node.children:
                    await _collect(child, current_depth=current_depth + 1)
                return
            if node.type != "file" or current_depth > inline_depth:
                return
            if is_binary_file_path(node.path):
                return
            file_size = node.size if node.size is not None else INLINE_CONTENT_MAX_SIZE + 1
            if (
                file_size > INLINE_CONTENT_MAX_SIZE
                or total_bytes + file_size > INLINE_CONTENT_TOTAL_MAX
            ):
                return
            try:
                result = await self.read_file_content(node.path, skip_metadata_check=True)
            except Exception:
                return
            if result.file_kind == "text" and result.content is not None and result.language:
                total_bytes += len(result.content.encode("utf-8"))
                contents[node.path] = {"content": result.content, "language": result.language}

        tree = await self._list_files_recursive(path, max_depth=max_depth)
        await _collect(tree, current_depth=0)
        return tree, contents

    async def read_file_content(
        self,
        file_path: str,
        *,
        skip_metadata_check: bool = False,
    ) -> FileContentResponse:
        mime_type = guess_mime_type(file_path)
        entry_size: int | None = None
        if not skip_metadata_check:
            info = await self._get_file_info(file_path)
            if info.is_dir:
                raise SandboxOperationError(
                    "read_file_content", f"path '{file_path}' is a directory"
                )
            entry_size = info.size

        if is_image_file_path(file_path, include_svg=False):
            return FileContentResponse(
                path=file_path,
                file_kind="image",
                mime_type=mime_type or "application/octet-stream",
            )

        if entry_size is not None and entry_size > MAX_FILE_CONTENT_SIZE:
            return FileContentResponse(
                path=file_path,
                file_kind="binary",
                mime_type=mime_type,
                message="File too big. Open VS Code to view.",
                too_big=True,
            )

        if is_binary_file_path(file_path):
            return FileContentResponse(
                path=file_path,
                file_kind="binary",
                mime_type=mime_type,
                message="Binary preview is not supported here. Open VS Code to view.",
            )

        content = await self.read_file(file_path)
        if len(content) > MAX_FILE_CONTENT_SIZE:
            return FileContentResponse(
                path=file_path,
                file_kind="binary",
                mime_type=mime_type,
                message="File too big. Open VS Code to view.",
                too_big=True,
            )
        return FileContentResponse(
            path=file_path,
            content=content,
            language=detect_language(file_path),
            mime_type=mime_type,
        )

    async def watch_dir(
        self,
        path: str,
        on_event: Any,
        on_exit: Any,
        *,
        timeout: int = 0,
        recursive: bool = True,
    ) -> Any:
        await self._ensure_sandbox_connection()
        task = asyncio.create_task(
            self._watch_poll_loop(
                path=path,
                on_event=on_event,
                on_exit=on_exit,
                timeout=timeout,
                recursive=recursive,
            )
        )
        return _PollingWatchHandle(task)

    async def expose_port(self, port: int) -> str:
        await self._ensure_sandbox_connection()
        payload = await self._api_request(
            "GET",
            f"/sandbox/{self.provider_sandbox_id}/ports/{port}/preview-url",
        )
        url = str(_field(payload, "url", default="") or "")
        token = _field(payload, "token")
        if token and "token=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}token={token}"
        if not url:
            raise SandboxOperationError(
                "expose_port", f"Daytona did not return a preview URL: {payload}"
            )
        return url

    async def get_host(self) -> str:
        preview_url = await self.expose_port(self._config.vscode_port)
        return urlparse(preview_url).netloc

    def get_mcp_client(self, sandbox_url: str) -> Client:
        mcp_url = sandbox_url.rstrip("/") + "/mcp/"
        if self.mcp_client is None:
            self.mcp_client = Client(mcp_url, timeout=self._config.mcp.timeout)
        return self.mcp_client

    async def _write_bytes(self, file_path: str, content: bytes) -> None:
        encoded = base64.b64encode(content).decode("ascii")
        script = (
            "from pathlib import Path\n"
            "import base64\n"
            f"path = Path({file_path!r})\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            f"path.write_bytes(base64.b64decode({encoded!r}))\n"
        )
        await self.run_command(f"python3 - <<'PY'\n{script}PY", timeout=120)

    async def _list_files_recursive(
        self,
        path: str,
        max_depth: int = 10,
        _current_depth: int = 0,
    ) -> FileTreeNode:
        basename = os.path.basename(path.rstrip("/")) or path
        entries = await self._list_directory(path)
        children: list[FileTreeNode] = []
        for entry in entries:
            if entry.is_dir:
                if entry.name in EXCLUDED_DIRS:
                    continue
                if _current_depth < max_depth:
                    try:
                        children.append(
                            await self._list_files_recursive(
                                entry.path,
                                max_depth=max_depth,
                                _current_depth=_current_depth + 1,
                            )
                        )
                    except Exception:
                        children.append(
                            FileTreeNode(
                                name=entry.name,
                                path=entry.path,
                                type="directory",
                                children=[],
                            )
                        )
                else:
                    children.append(
                        FileTreeNode(
                            name=entry.name,
                            path=entry.path,
                            type="directory",
                            children=[],
                        )
                    )
            else:
                children.append(
                    FileTreeNode(name=entry.name, path=entry.path, type="file", size=entry.size)
                )
        children.sort(key=lambda n: (0 if n.type == "directory" else 1, n.name.lower()))
        return FileTreeNode(name=basename, path=path, type="directory", children=children)

    async def _list_directory(self, path: str) -> list[_DaytonaFileInfo]:
        payload = await self._toolbox_request("GET", "/files/", params={"path": path})
        if not isinstance(payload, list):
            raise SandboxOperationError("list_files", f"Unexpected Daytona file list: {payload}")
        entries: list[_DaytonaFileInfo] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(_field(item, "name", default=""))
            if not name:
                continue
            entries.append(
                _DaytonaFileInfo(
                    name=name,
                    path=posixpath.join(path.rstrip("/"), name),
                    is_dir=bool(_field(item, "isDir", "is_dir", default=False)),
                    size=_field(item, "size"),
                    mod_time=_field(item, "modTime", "mod_time"),
                )
            )
        return entries

    async def _get_file_info(self, path: str) -> _DaytonaFileInfo:
        payload = await self._toolbox_request("GET", "/files/info", params={"path": path})
        if not isinstance(payload, dict):
            raise SandboxOperationError("get_file_info", f"Unexpected Daytona file info: {payload}")
        return _DaytonaFileInfo(
            name=str(_field(payload, "name", default=os.path.basename(path))),
            path=path,
            is_dir=bool(_field(payload, "isDir", "is_dir", default=False)),
            size=_field(payload, "size"),
            mod_time=_field(payload, "modTime", "mod_time"),
        )

    async def _snapshot_tree(
        self,
        path: str,
        *,
        recursive: bool,
    ) -> dict[str, tuple[bool, int | None, str | None]]:
        snapshot: dict[str, tuple[bool, int | None, str | None]] = {}

        async def _walk(directory: str, depth: int) -> None:
            entries = await self._list_directory(directory)
            for entry in entries:
                snapshot[entry.path] = (entry.is_dir, entry.size, entry.mod_time)
                if entry.is_dir and recursive and depth < 50 and entry.name not in EXCLUDED_DIRS:
                    await _walk(entry.path, depth + 1)

        root_info = await self._get_file_info(path)
        snapshot[path] = (root_info.is_dir, root_info.size, root_info.mod_time)
        if root_info.is_dir:
            await _walk(path, 0)
        return snapshot

    async def _watch_poll_loop(
        self,
        *,
        path: str,
        on_event: Any,
        on_exit: Any,
        timeout: int,
        recursive: bool,
    ) -> None:
        exc: Exception | None = None
        try:
            deadline = None if timeout <= 0 else asyncio.get_running_loop().time() + timeout
            previous = await self._snapshot_tree(path, recursive=recursive)
            while deadline is None or asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(1)
                current = await self._snapshot_tree(path, recursive=recursive)
                previous_paths = set(previous)
                current_paths = set(current)
                for removed in sorted(previous_paths - current_paths):
                    await self._maybe_await(
                        on_event(_DaytonaWatchEvent("remove", removed, removed))
                    )
                for created in sorted(current_paths - previous_paths):
                    await self._maybe_await(
                        on_event(_DaytonaWatchEvent("create", created, created))
                    )
                for candidate in sorted(previous_paths & current_paths):
                    if previous[candidate] != current[candidate] and not current[candidate][0]:
                        await self._maybe_await(
                            on_event(_DaytonaWatchEvent("write", candidate, candidate))
                        )
                previous = current
        except asyncio.CancelledError:
            raise
        except Exception as error:
            exc = error
            logger.debug("Daytona file watcher exited with error", exc_info=True)
        finally:
            await self._maybe_await(on_exit(exc))

    async def _ensure_sandbox_connection(self) -> None:
        if not self.provider_sandbox_id or self.provider_sandbox_id == "pending":
            raise SandboxNotInitializedError(
                f"Sandbox not yet initialized provider={self.provider}"
            )
        status = await self.get_status()
        if status == SandboxStatus.PAUSED:
            await self._api_request("POST", f"/sandbox/{self.provider_sandbox_id}/start")
            await self._wait_for_started(timeout=self._config.sandbox.timeout_seconds)
        elif status in {SandboxStatus.DELETED, SandboxStatus.ERROR}:
            raise SandboxNotFoundException(self.provider_sandbox_id)

    async def _wait_for_started(self, *, timeout: int) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            sandbox = await self._get_remote_sandbox()
            self.sandbox = sandbox
            state = _state_value(_field(sandbox, "state"))
            self.status = self._to_sandbox_status(state)
            if state in _STARTED_STATES:
                return
            if state in _ERROR_STATES or state in _DELETED_STATES:
                raise SandboxCreationError(f"Daytona sandbox failed to start: {sandbox}")
            if asyncio.get_running_loop().time() >= deadline:
                raise SandboxTimeoutException(self.provider_sandbox_id, "wait_for_started")
            await asyncio.sleep(1)

    async def _get_remote_sandbox(self) -> dict[str, Any]:
        return await self._api_request("GET", f"/sandbox/{self.provider_sandbox_id}")

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> Any:
        url = self._api_url(path)
        async with httpx.AsyncClient(timeout=timeout or 30) as client:
            response = await client.request(
                method,
                url,
                json=json,
                params=params,
                headers=self._headers(),
            )
        return self._decode_response(method, url, response, sandbox_not_found=True)

    async def _toolbox_request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> Any:
        url = self._toolbox_url(path)
        async with httpx.AsyncClient(timeout=timeout or 30) as client:
            response = await client.request(
                method,
                url,
                json=json,
                params=params,
                headers=self._headers(),
            )
        return self._decode_response(method, url, response, sandbox_not_found=False)

    def _decode_response(
        self,
        method: str,
        url: str,
        response: httpx.Response,
        *,
        sandbox_not_found: bool,
    ) -> Any:
        if response.status_code == 404 and sandbox_not_found:
            raise SandboxNotFoundException(self.provider_sandbox_id)
        if response.status_code in {401, 403}:
            raise SandboxAuthenticationError(response.text)
        if response.status_code >= 400:
            raise SandboxOperationError(
                method.lower(),
                f"Daytona API {response.status_code} for {url}: {response.text}",
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text

    def _api_url(self, path: str) -> str:
        base = self._config.sandbox.daytona_api_url.rstrip("/") + "/"
        return urljoin(base, path.lstrip("/"))

    def _toolbox_url(self, path: str) -> str:
        sandbox = self.sandbox or {}
        toolbox_proxy_url = str(
            _field(sandbox, "toolboxProxyUrl", "toolbox_proxy_url", default="") or ""
        ).rstrip("/")
        if not toolbox_proxy_url:
            raise SandboxOperationError(
                "toolbox_url",
                "Daytona sandbox response does not include toolboxProxyUrl",
            )
        return f"{toolbox_proxy_url}/{self.provider_sandbox_id}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-Daytona-Source": "ii-agent"}
        if self._config.sandbox.daytona_api_key:
            headers["Authorization"] = f"Bearer {self._config.sandbox.daytona_api_key}"
        return headers

    @staticmethod
    async def _maybe_await(result: Any) -> None:
        if inspect.isawaitable(result):
            await result

    @staticmethod
    async def _call_terminal_callback(callback: TerminalDataCallback, data: bytes) -> None:
        result = callback(data)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _to_sandbox_status(raw_state: Any) -> SandboxStatus:
        state = _state_value(raw_state)
        if state in _STARTED_STATES:
            return SandboxStatus.RUNNING
        if state in _PENDING_STATES:
            return SandboxStatus.INITIALIZING
        if state in _PAUSED_STATES:
            return SandboxStatus.PAUSED
        if state in _DELETED_STATES:
            return SandboxStatus.DELETED
        return SandboxStatus.ERROR

    @staticmethod
    def _metadata_from_sandbox(sandbox: dict[str, Any]) -> dict[str, Any]:
        labels = _field(sandbox, "labels", default={})
        return dict(labels or {}) if isinstance(labels, dict) else {}

    @classmethod
    def _build_metadata(
        cls,
        cfg: Settings,
        sandbox_id: str,
        session_id: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, str]:
        sandbox_metadata = {
            "ii_sandbox_id": sandbox_id,
            "session_id": session_id,
            "provider": "daytona",
            "env": str(cfg.environment),
        }
        if cfg.sandbox.daytona_snapshot:
            sandbox_metadata["snapshot"] = cfg.sandbox.daytona_snapshot
        else:
            sandbox_metadata["image"] = cfg.sandbox.daytona_default_image
        if metadata:
            sandbox_metadata.update(
                {str(key): _json_value(value) for key, value in metadata.items()}
            )
        return sandbox_metadata

    @classmethod
    def _build_create_payload(
        cls,
        cfg: Settings,
        sandbox_id: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        allow_list = ",".join(cfg.sandbox.daytona_network_allow_list) or None
        timeout_minutes = max(1, math.ceil(cfg.sandbox.timeout_seconds / 60))
        sandbox_user = cfg.sandbox.user.rstrip("/") or "/home/user"
        os_user = sandbox_user.removeprefix("/home/").lstrip("/") or "daytona"
        if "/" in os_user:
            os_user = os.path.basename(sandbox_user) or "daytona"
        body: dict[str, Any] = {
            "name": _sanitize_name(f"ii-agent-{sandbox_id}"),
            "user": os_user,
            "env": {"HOME": cfg.sandbox.user},
            "labels": metadata,
            "public": cfg.sandbox.daytona_public_preview,
            "target": cfg.sandbox.daytona_target,
            "autoStopInterval": cfg.sandbox.daytona_auto_stop_interval,
            "autoDeleteInterval": timeout_minutes if cfg.sandbox.daytona_ephemeral else None,
            "networkBlockAll": cfg.sandbox.daytona_network_block_all,
            "networkAllowList": allow_list,
        }
        if cfg.sandbox.daytona_snapshot:
            body["snapshot"] = cfg.sandbox.daytona_snapshot
        else:
            body["buildInfo"] = {"dockerfileContent": f"FROM {cfg.sandbox.daytona_default_image}\n"}
        return {key: value for key, value in body.items() if value is not None}
