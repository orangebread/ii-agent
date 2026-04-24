#!/usr/bin/env python3
"""Python-backed preflight helpers for scripts/start.sh."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import httpx
import urllib3
from dotenv import load_dotenv
from google.cloud import storage as gcs_storage
from minio import Minio
from redis.asyncio import Redis

from ii_agent.core.db.base import _prepare_asyncpg_url
from ii_agent.core.config.settings import get_settings
from ii_agent.core.runtime_capabilities import codex_app_server_workflows_enabled


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def prime_environment() -> None:
    configured_env = Path(os.environ.get("II_AGENT_ENV_FILE", str(DEFAULT_ENV_FILE)))
    load_dotenv(dotenv_path=configured_env, override=False)


def is_local_host(host: str | None) -> bool:
    return bool(host) and host in LOCAL_HOSTS


def summarize_http_error(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "unknown")
    body = " ".join(response.text.strip().split())
    if len(body) > 240:
        body = f"{body[:240]}..."
    return f"status={response.status_code} content-type={content_type} body={body or '<empty>'}"


def emit_facts() -> int:
    settings = get_settings()
    db_url = settings.database.url or ""
    redis_url = settings.redis.session_url or ""
    db_host = urlparse(db_url).hostname
    redis_host = urlparse(redis_url).hostname
    minio_host = ""
    if settings.storage.provider == "minio":
        minio_host = settings.storage.minio_endpoint.split(":", 1)[0]

    sandbox_ready = "1"
    if settings.sandbox.provider == "e2b" and not settings.sandbox.e2b_api_key:
        sandbox_ready = "0"
    elif settings.sandbox.provider == "daytona" and not settings.sandbox.daytona_api_url:
        sandbox_ready = "0"

    facts = {
        "RUNTIME_ENVIRONMENT": settings.environment,
        "RUNTIME_DATABASE_URL": db_url,
        "RUNTIME_DATABASE_IS_LOCAL": "1" if is_local_host(db_host) else "0",
        "RUNTIME_REDIS_ENABLED": "1" if settings.redis.session_enabled else "0",
        "RUNTIME_REDIS_URL": redis_url,
        "RUNTIME_REDIS_IS_LOCAL": "1" if is_local_host(redis_host) else "0",
        "RUNTIME_STORAGE_PROVIDER": settings.storage.provider,
        "RUNTIME_STORAGE_LOCAL_DIR": settings.storage.local_base_dir,
        "RUNTIME_STORAGE_MINIO_ENDPOINT": settings.storage.minio_endpoint,
        "RUNTIME_STORAGE_MINIO_IS_LOCAL": "1" if is_local_host(minio_host) else "0",
        "RUNTIME_STORAGE_GCS_BUCKET": settings.storage.bucket_name or "",
        "RUNTIME_STORAGE_GCS_PROJECT": settings.storage.project_id or "",
        "RUNTIME_MODEL_CONFIGS_PRESENT": "1" if settings.model_configs else "0",
        "RUNTIME_SANDBOX_PROVIDER": settings.sandbox.provider,
        "RUNTIME_SANDBOX_DOCKER_IMAGE": settings.sandbox.docker_image,
        "RUNTIME_SANDBOX_DAYTONA_API_URL": settings.sandbox.daytona_api_url,
        "RUNTIME_SANDBOX_DAYTONA_API_KEY_PRESENT": "1" if settings.sandbox.daytona_api_key else "0",
        "RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE": settings.sandbox.daytona_default_image,
        "RUNTIME_SANDBOX_CODEX_CLI_PACKAGE": (
            f"@openai/codex@{settings.sandbox.codex_cli_version}"
            if settings.sandbox.codex_cli_version
            else "@openai/codex"
        ),
        "RUNTIME_SANDBOX_READY": sandbox_ready,
        "RUNTIME_CODEX_APP_SERVER_WORKFLOWS_ENABLED": "1"
        if codex_app_server_workflows_enabled(settings)
        else "0",
        "RUNTIME_CODEX_APP_SERVER_SMOKE_VERIFIED": "1"
        if settings.codex_app_server_smoke_verified
        else "0",
    }

    for key, value in facts.items():
        print(f"{key}={shlex.quote(str(value))}")
    return 0


async def probe_database() -> int:
    settings = get_settings()
    database_url, connect_args = _prepare_asyncpg_url(settings.database.url or "")
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    database_url = database_url.replace("postgres+asyncpg://", "postgres://", 1)
    conn = await asyncpg.connect(dsn=database_url, timeout=5, **connect_args)
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()
    return 0


async def probe_redis() -> int:
    settings = get_settings()
    if not settings.redis.session_enabled:
        return 0

    client = Redis.from_url(
        settings.redis.session_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        pong = await client.ping()
        if not pong:
            raise RuntimeError("Redis ping returned falsy response")
    finally:
        await client.aclose()
    return 0


def probe_storage() -> int:
    settings = get_settings()
    storage = settings.storage

    if storage.provider == "local":
        Path(storage.local_base_dir).expanduser().mkdir(parents=True, exist_ok=True)
        return 0

    if storage.provider == "minio":
        if not storage.bucket_name:
            raise ValueError("MinIO requires STORAGE_BUCKET_NAME")
        client = Minio(
            storage.minio_endpoint,
            access_key=storage.minio_access_key,
            secret_key=storage.minio_secret_key,
            region=storage.minio_region,
            secure=storage.minio_secure,
            http_client=urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=5, read=5),
                retries=False,
            ),
        )
        if not client.bucket_exists(storage.bucket_name):
            client.make_bucket(storage.bucket_name)
        return 0

    if storage.provider == "gcs":
        if not storage.project_id or not storage.bucket_name:
            raise ValueError("GCS requires STORAGE_PROJECT_ID and STORAGE_BUCKET_NAME")
        client = gcs_storage.Client(project=storage.project_id)
        bucket = client.bucket(storage.bucket_name)
        if not bucket.exists(timeout=5):
            raise RuntimeError(
                f"GCS bucket '{storage.bucket_name}' is not reachable in project '{storage.project_id}'"
            )
        return 0

    raise ValueError(f"Unsupported storage provider: {storage.provider}")


def probe_app() -> int:
    from ii_agent.app import create_app

    create_app()
    return 0


def probe_libmagic() -> int:
    import magic

    magic.from_buffer(b"ii-agent", mime=True)
    return 0


def check_port(host: str, port: int) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    finally:
        sock.close()
    return 0


def _resolve_container_runtime() -> str:
    for candidate in ("podman", "docker"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("Neither podman nor docker is installed")


def probe_codex_app_server_image() -> int:
    settings = get_settings()
    runtime = _resolve_container_runtime()
    image = settings.sandbox.docker_image

    inspect = subprocess.run(
        [runtime, "image", "inspect", image],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if inspect.returncode != 0:
        raise RuntimeError(
            f"Sandbox Docker image {image!r} is not present; Codex App Server "
            "contract cannot be verified until the image is built."
        )

    script = (
        "set -euo pipefail; "
        "command -v codex >/dev/null; "
        "codex --version >/dev/null; "
        "codex app-server --help >/dev/null"
    )
    probe = subprocess.run(
        [runtime, "run", "--rm", "--entrypoint", "bash", image, "-lc", script],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    if probe.returncode != 0:
        details = (probe.stderr or probe.stdout or "").strip()
        raise RuntimeError(
            "Configured sandbox Docker image does not expose a working "
            f"`codex app-server` command. Details: {details}"
        )

    _probe_codex_app_server_initialize(runtime=runtime, image=image)
    return 0


def probe_daytona_api() -> int:
    settings = get_settings()
    if settings.sandbox.provider != "daytona":
        return 0

    api_url = settings.sandbox.daytona_api_url.rstrip("/")
    if not api_url:
        raise ValueError("SANDBOX_DAYTONA_API_URL is required for SANDBOX_PROVIDER=daytona")

    headers = {"Accept": "application/json", "X-Daytona-Source": "ii-agent-preflight"}
    if settings.sandbox.daytona_api_key:
        headers["Authorization"] = f"Bearer {settings.sandbox.daytona_api_key}"

    response = httpx.get(
        f"{api_url}/sandbox",
        headers=headers,
        timeout=5,
    )
    if response.status_code in {401, 403}:
        raise RuntimeError(
            "Daytona API is reachable but rejected credentials; set SANDBOX_DAYTONA_API_KEY"
        )
    if response.status_code >= 500:
        raise RuntimeError(
            f"Daytona API is reachable but unhealthy: {summarize_http_error(response)}"
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Daytona API probe failed: {summarize_http_error(response)}")
    return 0


def probe_daytona_health() -> int:
    settings = get_settings()
    if settings.sandbox.provider != "daytona":
        return 0

    api_url = settings.sandbox.daytona_api_url.rstrip("/")
    if not api_url:
        raise ValueError("SANDBOX_DAYTONA_API_URL is required for SANDBOX_PROVIDER=daytona")

    response = httpx.get(
        f"{api_url}/health",
        headers={"Accept": "application/json", "X-Daytona-Source": "ii-agent-preflight"},
        timeout=5,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Daytona health probe failed: {summarize_http_error(response)}")
    return 0


def _probe_codex_app_server_initialize(*, runtime: str, image: str) -> None:
    proc = subprocess.Popen(
        [
            runtime,
            "run",
            "-i",
            "--rm",
            "--entrypoint",
            "codex",
            image,
            "app-server",
            "--listen",
            "stdio://",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            json.dumps(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "ii_agent_preflight",
                            "title": "II Agent Preflight",
                            "version": "0.1.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()

        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            events = selector.select(timeout=max(0.1, min(1, deadline - time.monotonic())))
            if not events:
                continue
            line = proc.stdout.readline()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("id") != 1:
                continue
            if "error" in payload:
                raise RuntimeError(f"Codex app-server initialize failed: {payload['error']}")
            if not isinstance(payload.get("result"), dict):
                raise RuntimeError("Codex app-server initialize returned an invalid result")
            return

        raise RuntimeError("Timed out waiting for Codex app-server initialize response")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="II-Agent startup preflight helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("facts")
    subparsers.add_parser("probe-database")
    subparsers.add_parser("probe-redis")
    subparsers.add_parser("probe-storage")
    subparsers.add_parser("probe-libmagic")
    subparsers.add_parser("probe-app")
    subparsers.add_parser("probe-codex-app-server-image")
    subparsers.add_parser("probe-daytona-api")
    subparsers.add_parser("probe-daytona-health")

    port_parser = subparsers.add_parser("check-port")
    port_parser.add_argument("--host", required=True)
    port_parser.add_argument("--port", type=int, required=True)

    return parser.parse_args()


def main() -> int:
    prime_environment()
    args = parse_args()

    if args.command == "facts":
        return emit_facts()
    if args.command == "probe-database":
        return asyncio.run(probe_database())
    if args.command == "probe-redis":
        return asyncio.run(probe_redis())
    if args.command == "probe-storage":
        return probe_storage()
    if args.command == "probe-libmagic":
        return probe_libmagic()
    if args.command == "probe-app":
        return probe_app()
    if args.command == "probe-codex-app-server-image":
        return probe_codex_app_server_image()
    if args.command == "probe-daytona-api":
        return probe_daytona_api()
    if args.command == "probe-daytona-health":
        return probe_daytona_health()
    if args.command == "check-port":
        return check_port(args.host, args.port)

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - operational entrypoint
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
