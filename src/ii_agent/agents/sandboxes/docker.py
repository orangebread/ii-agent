"""Docker/Podman sandbox provider implementation.

This provider is aimed at local development and Codex runtime execution.
It intentionally does not attempt full E2B feature parity.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import pty
import shlex
import shutil
import termios
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import IO, Any, AsyncIterator, Dict, List, Literal, Optional

from fastmcp import Client

from ii_agent.agents.sandboxes.base import Sandbox
from ii_agent.agents.sandboxes.exceptions import (
    SandboxCreationError,
    SandboxNotFoundException,
    SandboxOperationError,
    SandboxTimeoutException,
)
from ii_agent.agents.sandboxes.schemas import (
    EXCLUDED_DIRS,
    BINARY_EXTENSIONS,
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
from ii_agent.agents.sandboxes.terminal import LiveTerminalHandle, TerminalDataCallback
from ii_agent.agents.sandboxes.types import SandboxProviderType, SandboxStatus
from ii_agent.core.config.settings import Settings, get_settings
from ii_agent.core.logger import logger


_DEFAULT_RUNTIME_IMAGE = "ii-agent-codex-sandbox:local"
_DEFAULT_CODEX_CLI_VERSION = "0.124.0"
_RUNTIME_BUILD_LOCK = asyncio.Lock()
_RUNTIME_CANDIDATES = ("podman", "docker")
_CONTAINER_START_CMD = (
    "mkdir -p /app /workspace /home/user/.codex && touch /app/.user_env.sh && sleep infinity"
)


def _codex_cli_package_spec(config: Settings) -> str:
    version = str(
        getattr(config.sandbox, "codex_cli_version", _DEFAULT_CODEX_CLI_VERSION)
        or _DEFAULT_CODEX_CLI_VERSION
    ).strip()
    return f"@openai/codex@{version}" if version else "@openai/codex"


def _runtime_dockerfile(config: Settings) -> str:
    codex_package = _codex_cli_package_spec(config)
    quoted_codex_package = shlex.quote(codex_package)
    return f"""
FROM node:22-bookworm

LABEL ii_agent.codex_cli_package={json.dumps(codex_package)}

RUN apt-get update \\
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\
        bash \\
        ca-certificates \\
        curl \\
        git \\
        procps \\
        python3 \\
        python3-pip \\
        python3-venv \\
        ripgrep \\
        tar \\
    && rm -rf /var/lib/apt/lists/*

RUN npm i -g {quoted_codex_package}
RUN mkdir -p /app /workspace /home/user/.codex && touch /app/.user_env.sh

ENV HOME=/home/user
WORKDIR /workspace
CMD ["bash", "-lc", "{_CONTAINER_START_CMD}"]
""".strip()


_FILE_WRITE_SCRIPT = """
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(sys.stdin.buffer.read())
""".strip()
_FILE_READ_SCRIPT = """
from pathlib import Path
import sys

sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())
""".strip()
_STAT_SCRIPT = """
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
payload = {
    "exists": path.exists(),
    "is_dir": path.is_dir(),
    "size": path.stat().st_size if path.exists() and path.is_file() else None,
}
print(json.dumps(payload))
""".strip()
_LIST_FILES_SCRIPT = """
from pathlib import Path
import json
import os
import sys

root = Path(sys.argv[1])
max_depth = int(sys.argv[2])
inline_depth = int(sys.argv[3])
excluded_dirs = set(json.loads(sys.argv[4]))
binary_exts = set(json.loads(sys.argv[5]))
inline_size_max = int(sys.argv[6])
inline_total_max = int(sys.argv[7])

contents = {}
total_bytes = 0

def detect_language(path: str) -> str:
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".json": "json",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sql": "sql",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".xml": "xml",
        ".svg": "xml",
        ".graphql": "graphql",
        ".prisma": "prisma",
        ".env": "bash",
        ".txt": "plaintext",
    }
    basename = os.path.basename(path).lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename == "makefile":
        return "makefile"
    return ext_map.get(Path(path).suffix.lower(), "plaintext")

def walk(path: Path, depth: int):
    name = path.name or str(path)
    if not path.exists():
        return {"name": name, "path": str(path), "type": "directory", "children": []}
    if path.is_file():
        return {"name": name, "path": str(path), "type": "file", "size": path.stat().st_size}

    children = []
    if depth < max_depth:
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.is_dir() and child.name in excluded_dirs:
                continue
            children.append(walk(child, depth + 1))
    return {"name": name, "path": str(path), "type": "directory", "children": children}

def collect(node, depth: int):
    global total_bytes
    if node["type"] == "directory":
        for child in node.get("children", []):
            collect(child, depth + 1)
        return

    path = node["path"]
    ext = Path(path).suffix.lower()
    if ext in binary_exts:
        return
    size = node.get("size") or 0
    if size > inline_size_max:
        return
    if inline_depth >= 0 and depth > inline_depth:
        return
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return
    encoded = len(text.encode("utf-8"))
    if total_bytes + encoded > inline_total_max:
        return
    total_bytes += encoded
    contents[path] = {"content": text, "language": detect_language(path)}

tree = walk(root, 0)
collect(tree, 0)
print(json.dumps({"tree": tree, "contents": contents}))
""".strip()


@dataclass(slots=True)
class _ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


class DockerLiveTerminalHandle(LiveTerminalHandle):
    """PTY-backed handle around ``docker exec -it``."""

    def __init__(
        self,
        *,
        process: asyncio.subprocess.Process,
        master_fd: int,
        reader_task: asyncio.Task[None],
    ) -> None:
        self._process = process
        self._master_fd = master_fd
        self._reader_task = reader_task
        self._closed = False

    @property
    def pid(self) -> int:
        return self._process.pid

    async def send_input(self, data: bytes) -> None:
        await asyncio.to_thread(os.write, self._master_fd, data)

    async def resize(self, cols: int, rows: int) -> None:
        await asyncio.to_thread(_set_winsize, self._master_fd, rows, cols)

    async def kill(self) -> bool:
        if self._process.returncode is not None:
            return False
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()
        return True

    async def disconnect(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reader_task.cancel()
        with contextlib.suppress(OSError):
            os.close(self._master_fd)

    async def wait(self) -> int | None:
        return await self._process.wait()


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    import fcntl
    import struct

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _resolve_runtime_binary() -> str:
    for candidate in _RUNTIME_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    raise SandboxCreationError("Neither podman nor docker is installed on this machine.")


def _container_name(sandbox_id: str) -> str:
    return f"ii-agent-sandbox-{sandbox_id}"


def _project_name() -> str:
    return os.getenv("DEV_PROJECT_NAME") or os.getenv("COMPOSE_PROJECT_NAME") or "ii-agent-dev"


def _quote(path: str) -> str:
    return shlex.quote(path)


def _coerce_content(content: str | bytes | IO) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raw = content.read()
    return raw.encode("utf-8") if isinstance(raw, str) else raw


async def _run_subprocess(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int | float | None = None,
) -> _ProcessResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return _ProcessResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr)


class DockerSandbox(Sandbox):
    """Local Docker/Podman-backed sandbox provider."""

    PROVIDER: SandboxProviderType = SandboxProviderType.DOCKER

    def __init__(
        self,
        sandbox_id: str,
        session_id: str,
        provider_sandbox_id: str,
        *,
        status: SandboxStatus = SandboxStatus.NOT_INITIALIZED,
        metadata: Optional[Dict[str, Any]] = None,
        expired_at: Optional[datetime] = None,
        config: Optional[Settings] = None,
        runtime_binary: Optional[str] = None,
    ) -> None:
        super().__init__(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id=provider_sandbox_id,
            status=status,
            metadata=metadata,
            expired_at=expired_at,
        )
        self._config = config or get_settings()
        self._runtime_binary = runtime_binary or _resolve_runtime_binary()

    def get_provider_id(self) -> str:
        return self.provider_sandbox_id

    @property
    def upload_path(self) -> str:
        return self._config.workspace_upload_path

    async def get_info(self) -> SandboxInfo:
        return SandboxInfo(
            id=self.sandbox_id,
            session_id=self.session_id,
            status=await self.get_status(),
            expired_at=self.expired_at,
            provider=SandboxProviderType.DOCKER,
            vscode_url=None,
        )

    async def get_status(self) -> SandboxStatus:
        state = await self._inspect_state()
        if state == "running":
            return SandboxStatus.RUNNING
        if state in {"created", "exited", "paused", "restarting"}:
            return SandboxStatus.PAUSED
        if state in {"dead", "removing"}:
            return SandboxStatus.ERROR
        return SandboxStatus.ERROR

    @classmethod
    async def create(
        cls,
        sandbox_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "DockerSandbox":
        cfg = get_settings()
        runtime_binary = _resolve_runtime_binary()
        await cls._ensure_runtime_image(cfg, runtime_binary)
        project_name = _project_name()

        sandbox_metadata = {
            "ii_sandbox_id": sandbox_id,
            "session_id": session_id,
            "image": cfg.sandbox.docker_image,
            "project_name": project_name,
            "runtime": runtime_binary,
        }
        if metadata:
            sandbox_metadata.update(metadata)

        result = await _run_subprocess(
            [
                runtime_binary,
                "run",
                "-d",
                "--init",
                "--name",
                _container_name(sandbox_id),
                "--label",
                "ii_agent.managed=true",
                "--label",
                "ii_agent.role=sandbox",
                "--label",
                f"ii_agent.sandbox_id={sandbox_id}",
                "--label",
                f"ii_agent.session_id={session_id}",
                "--label",
                f"ii_agent.project_name={project_name}",
                "-e",
                f"HOME={cfg.sandbox.user}",
                cfg.sandbox.docker_image,
                "bash",
                "-lc",
                _CONTAINER_START_CMD,
            ],
            timeout=120,
        )
        if result.exit_code != 0:
            raise SandboxCreationError(
                result.stderr_text or result.stdout_text or "docker run failed"
            )

        provider_sandbox_id = result.stdout_text.strip()
        expired_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.sandbox.timeout_seconds)
        logger.info(
            "Created Docker sandbox %s (provider: %s) with image %s",
            sandbox_id,
            provider_sandbox_id,
            cfg.sandbox.docker_image,
        )
        return cls(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id=provider_sandbox_id,
            status=SandboxStatus.RUNNING,
            metadata=sandbox_metadata,
            expired_at=expired_at,
            config=cfg,
            runtime_binary=runtime_binary,
        )

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        session_id: str,
        provider_sandbox_id: str,
    ) -> "DockerSandbox":
        cfg = get_settings()
        runtime_binary = _resolve_runtime_binary()
        instance = cls(
            sandbox_id=sandbox_id,
            session_id=session_id,
            provider_sandbox_id=provider_sandbox_id,
            metadata={"runtime": runtime_binary, "image": cfg.sandbox.docker_image},
            config=cfg,
            runtime_binary=runtime_binary,
        )
        await instance._ensure_container_running()
        instance.status = await instance.get_status()
        return instance

    async def pause(self) -> None:
        await self._ensure_container_exists()
        result = await _run_subprocess(
            [self._runtime_binary, "stop", self.provider_sandbox_id],
            timeout=30,
        )
        if result.exit_code != 0:
            raise SandboxOperationError("pause", result.stderr_text or result.stdout_text)
        self.status = SandboxStatus.PAUSED

    async def set_timeout(self, timeout_seconds: int) -> None:
        self.expired_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)

    async def run_command(
        self,
        command: str,
        background: bool = False,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        await self._ensure_container_running()
        args = [self._runtime_binary, "exec"]
        if background:
            args.append("-d")
        user = kwargs.get("user")
        if user:
            args.extend(["-u", str(user)])
        if cwd:
            args.extend(["-w", cwd])
        args.extend([self.provider_sandbox_id, "bash", "-lc", command])
        try:
            result = await _run_subprocess(args, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SandboxTimeoutException(self.sandbox_id, "run_command") from exc
        if result.exit_code != 0:
            raise SandboxOperationError(
                "run_command",
                result.stderr_text or result.stdout_text or f"Exit code: {result.exit_code}",
            )
        return result.stdout_text

    async def run_python_code(self, code: str) -> str:
        await self._ensure_container_running()
        try:
            result = await _run_subprocess(
                [self._runtime_binary, "exec", "-i", self.provider_sandbox_id, "python3", "-"],
                input_bytes=code.encode("utf-8"),
                timeout=120,
            )
        except asyncio.TimeoutError as exc:
            raise SandboxTimeoutException(self.sandbox_id, "run_python_code") from exc
        if result.exit_code != 0:
            raise SandboxOperationError(
                "run_python_code",
                result.stderr_text or result.stdout_text or f"Exit code: {result.exit_code}",
            )
        return result.stdout_text

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
        del timeout
        await self._ensure_container_running()
        master_fd, slave_fd = pty.openpty()
        _set_winsize(master_fd, rows, cols)

        args = [self._runtime_binary, "exec", "-i", "-t", "-w", cwd]
        args.extend(["-e", f"HOME={self._config.sandbox.user}"])
        for key, value in (envs or {}).items():
            args.extend(["-e", f"{key}={value}"])
        args.extend([self.provider_sandbox_id, "bash", "-l"])

        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
        )
        os.close(slave_fd)

        async def _reader() -> None:
            try:
                while True:
                    chunk = await asyncio.to_thread(os.read, master_fd, 4096)
                    if not chunk:
                        return
                    maybe_awaitable = on_data(chunk)
                    if inspect.isawaitable(maybe_awaitable):
                        await maybe_awaitable
            except asyncio.CancelledError:
                raise
            except OSError:
                return

        reader_task = asyncio.create_task(_reader())
        return DockerLiveTerminalHandle(
            process=process,
            master_fd=master_fd,
            reader_task=reader_task,
        )

    async def read_file(self, file_path: str) -> str:
        content = await self.download_file(file_path, format="text")
        if not isinstance(content, str):
            raise SandboxOperationError("read_file", f"File {file_path} is not text")
        return content

    async def write_file(
        self,
        file_path: str,
        content: str | bytes | IO,
    ) -> SandboxFileInfo:
        await self._ensure_container_running()
        result = await _run_subprocess(
            [
                self._runtime_binary,
                "exec",
                "-i",
                self.provider_sandbox_id,
                "python3",
                "-c",
                _FILE_WRITE_SCRIPT,
                file_path,
            ],
            input_bytes=_coerce_content(content),
            timeout=60,
        )
        if result.exit_code != 0:
            raise SandboxOperationError("write_file", result.stderr_text or result.stdout_text)
        return SandboxFileInfo(name=PurePosixPath(file_path).name, type="file", path=file_path)

    async def write_files(self, files: List[FileUpload]) -> List[SandboxFileInfo]:
        return [await self.write_file(file.path, file.content) for file in files]

    async def upload_file(
        self,
        file_content: str | bytes | IO,
        remote_file_path: str,
    ) -> bool:
        await self.write_file(remote_file_path, file_content)
        return True

    async def download_file(
        self,
        remote_file_path: str,
        format: Literal["text", "bytes"] = "text",
    ) -> Optional[str | bytes]:
        await self._ensure_container_running()
        result = await _run_subprocess(
            [
                self._runtime_binary,
                "exec",
                "-i",
                self.provider_sandbox_id,
                "python3",
                "-c",
                _FILE_READ_SCRIPT,
                remote_file_path,
            ],
            timeout=60,
        )
        if result.exit_code != 0:
            raise SandboxOperationError("download_file", result.stderr_text or result.stdout_text)
        if format == "bytes":
            return result.stdout
        return result.stdout.decode("utf-8", errors="replace")

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
        await self._ensure_container_running()
        result = await self.run_command(f"rm -rf {_quote(file_path)}")
        del result
        return True

    async def create_directory(
        self,
        directory_path: str,
        exist_ok: bool = False,
    ) -> bool:
        existed = await self.file_exists(directory_path)
        if existed and not exist_ok:
            raise SandboxOperationError(
                "create_directory", f"Directory {directory_path} already exists"
            )
        await self.run_command(f"mkdir -p {_quote(directory_path)}")
        return True

    async def file_exists(self, file_path: str) -> bool:
        payload = await self._stat_path(file_path)
        return bool(payload.get("exists"))

    async def list_files_with_contents(
        self,
        path: str,
        max_depth: int = 10,
        inline_content_max_depth: int | None = None,
    ) -> tuple[FileTreeNode, dict[str, dict[str, str]]]:
        await self._ensure_container_running()
        inline_depth = (
            INLINE_CONTENT_PREFETCH_DEPTH
            if inline_content_max_depth is None
            else inline_content_max_depth
        )
        payload = await self._run_python_json(
            _LIST_FILES_SCRIPT,
            [
                path,
                str(max_depth),
                str(inline_depth),
                json.dumps(sorted(EXCLUDED_DIRS)),
                json.dumps(sorted(BINARY_EXTENSIONS)),
                str(INLINE_CONTENT_MAX_SIZE),
                str(INLINE_CONTENT_TOTAL_MAX),
            ],
        )
        tree = FileTreeNode.model_validate(payload["tree"])
        contents = payload.get("contents") or {}
        return tree, contents

    async def read_file_content(
        self,
        file_path: str,
        *,
        skip_metadata_check: bool = False,
    ) -> FileContentResponse:
        mime_type = guess_mime_type(file_path)
        payload = await self._stat_path(file_path)
        if not payload.get("exists"):
            raise SandboxOperationError("read_file_content", f"File not found: {file_path}")
        if payload.get("is_dir"):
            raise SandboxOperationError("read_file_content", f"path '{file_path}' is a directory")

        if is_image_file_path(file_path, include_svg=False):
            return FileContentResponse(
                path=file_path,
                file_kind="image",
                mime_type=mime_type or "application/octet-stream",
            )

        size = payload.get("size")
        if not skip_metadata_check and isinstance(size, int) and size > MAX_FILE_CONTENT_SIZE:
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
        del path, on_event, on_exit, timeout, recursive
        raise SandboxOperationError(
            "watch_dir",
            "Directory watching is not supported by the Docker sandbox provider yet.",
        )

    async def expose_port(self, port: int) -> str:
        del port
        raise SandboxOperationError(
            "expose_port",
            "Port exposure is not supported by the Docker sandbox provider yet.",
        )

    async def get_host(self) -> str:
        raise SandboxOperationError(
            "get_host",
            "Host discovery is not supported by the Docker sandbox provider yet.",
        )

    def get_mcp_client(self, sandbox_url: str) -> Client:
        del sandbox_url
        raise SandboxOperationError(
            "get_mcp_client",
            "MCP exposure is not supported by the Docker sandbox provider yet.",
        )

    async def _ensure_container_exists(self) -> None:
        try:
            await self._inspect_state()
        except SandboxNotFoundException:
            raise

    async def _ensure_container_running(self) -> None:
        state = await self._inspect_state()
        if state == "running":
            self.status = SandboxStatus.RUNNING
            return
        if state == "paused":
            result = await _run_subprocess(
                [self._runtime_binary, "unpause", self.provider_sandbox_id]
            )
        elif state in {"created", "exited"}:
            result = await _run_subprocess(
                [self._runtime_binary, "start", self.provider_sandbox_id]
            )
        else:
            raise SandboxOperationError(
                "_ensure_container_running",
                f"Container {self.provider_sandbox_id} is in unsupported state: {state}",
            )
        if result.exit_code != 0:
            raise SandboxOperationError(
                "_ensure_container_running",
                result.stderr_text or result.stdout_text,
            )
        self.status = SandboxStatus.RUNNING

    async def _inspect_state(self) -> str:
        result = await _run_subprocess(
            [
                self._runtime_binary,
                "inspect",
                "--format",
                "{{.State.Status}}",
                self.provider_sandbox_id,
            ],
            timeout=30,
        )
        if result.exit_code != 0:
            raise SandboxNotFoundException(self.provider_sandbox_id)
        return result.stdout_text.strip()

    async def _stat_path(self, file_path: str) -> dict[str, Any]:
        return await self._run_python_json(_STAT_SCRIPT, [file_path])

    async def _run_python_json(self, script: str, args: list[str]) -> dict[str, Any]:
        await self._ensure_container_running()
        result = await _run_subprocess(
            [self._runtime_binary, "exec", "-i", self.provider_sandbox_id, "python3", "-", *args],
            input_bytes=script.encode("utf-8"),
            timeout=60,
        )
        if result.exit_code != 0:
            raise SandboxOperationError(
                "run_python_script", result.stderr_text or result.stdout_text
            )
        try:
            return json.loads(result.stdout_text)
        except json.JSONDecodeError as exc:
            raise SandboxOperationError("run_python_script", "Invalid JSON payload") from exc

    @classmethod
    async def _ensure_runtime_image(cls, config: Settings, runtime_binary: str) -> None:
        image = config.sandbox.docker_image
        inspect_result = await _run_subprocess(
            [runtime_binary, "image", "inspect", image],
            timeout=30,
        )
        if inspect_result.exit_code == 0:
            return
        if image != _DEFAULT_RUNTIME_IMAGE:
            raise SandboxCreationError(
                f"Docker image {image!r} was not found. Build or configure the runtime image first."
            )

        async with _RUNTIME_BUILD_LOCK:
            inspect_result = await _run_subprocess(
                [runtime_binary, "image", "inspect", image],
                timeout=30,
            )
            if inspect_result.exit_code == 0:
                return

            logger.info("Building local Docker sandbox image %s", image)
            build_result = await _run_subprocess(
                [runtime_binary, "build", "-t", image, "-"],
                input_bytes=_runtime_dockerfile(config).encode("utf-8"),
                timeout=1800,
            )
            if build_result.exit_code != 0:
                raise SandboxCreationError(
                    build_result.stderr_text or build_result.stdout_text or "docker build failed"
                )
