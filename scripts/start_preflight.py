#!/usr/bin/env python3
"""Python-backed preflight helpers for scripts/start.sh."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import urllib3
from dotenv import load_dotenv
from google.cloud import storage as gcs_storage
from minio import Minio
from redis.asyncio import Redis

from ii_agent.core.db.base import _prepare_asyncpg_url
from ii_agent.core.config.settings import get_settings


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def prime_environment() -> None:
    configured_env = Path(os.environ.get("II_AGENT_ENV_FILE", str(DEFAULT_ENV_FILE)))
    load_dotenv(dotenv_path=configured_env, override=False)


def is_local_host(host: str | None) -> bool:
    return bool(host) and host in LOCAL_HOSTS


def emit_facts() -> int:
    settings = get_settings()
    db_url = settings.database.url or ""
    redis_url = settings.redis.session_url or ""
    db_host = urlparse(db_url).hostname
    redis_host = urlparse(redis_url).hostname
    minio_host = ""
    if settings.storage.provider == "minio":
        minio_host = settings.storage.minio_endpoint.split(":", 1)[0]

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
        "RUNTIME_SANDBOX_READY": "0"
        if settings.sandbox.provider == "e2b" and not settings.sandbox.e2b_api_key
        else "1",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="II-Agent startup preflight helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("facts")
    subparsers.add_parser("probe-database")
    subparsers.add_parser("probe-redis")
    subparsers.add_parser("probe-storage")
    subparsers.add_parser("probe-libmagic")
    subparsers.add_parser("probe-app")

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
    if args.command == "check-port":
        return check_port(args.host, args.port)

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - operational entrypoint
        print(str(exc), file=sys.stderr)
        raise
