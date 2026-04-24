from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from ii_agent.core.config.settings import get_settings


pytestmark = [pytest.mark.smoke, pytest.mark.codex_smoke, pytest.mark.external]

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


def _container_runtime() -> str | None:
    for candidate in ("podman", "docker"):
        result = subprocess.run(
            ["sh", "-lc", f"command -v {candidate}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    return None


def _read_initialize_response(proc: subprocess.Popen[str]) -> dict:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
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
        if payload.get("id") == 1:
            return payload
    pytest.fail("Timed out waiting for Codex app-server initialize response")


def test_configured_docker_sandbox_exposes_codex_app_server_protocol():
    if os.getenv("II_AGENT_RUN_CODEX_SMOKE", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set II_AGENT_RUN_CODEX_SMOKE=1 to run Codex sandbox contract smoke tests")

    settings = get_settings()
    if settings.sandbox.provider != "docker":
        pytest.skip("This smoke test validates the local Docker sandbox image only")

    runtime = _container_runtime()
    if runtime is None:
        pytest.fail("Neither podman nor docker is available for Codex smoke testing")

    image = settings.sandbox.docker_image
    help_result = subprocess.run(
        [
            runtime,
            "run",
            "--rm",
            "--entrypoint",
            "bash",
            image,
            "-lc",
            "set -euo pipefail; command -v codex; codex --version; codex app-server --help >/dev/null",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )

    assert help_result.returncode == 0, help_result.stderr or help_result.stdout

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
        proc.stdin.write(
            json.dumps(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "ii_agent_smoke",
                            "title": "II Agent Smoke",
                            "version": "0.1.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        response = _read_initialize_response(proc)
        assert "error" not in response, response
        assert isinstance(response.get("result"), dict)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
