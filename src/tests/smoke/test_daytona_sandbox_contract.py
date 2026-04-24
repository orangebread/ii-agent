from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

from ii_agent.agents.sandboxes.daytona import DaytonaSandbox
from ii_agent.core.config.settings import get_settings


pytestmark = [pytest.mark.smoke, pytest.mark.sandbox_smoke, pytest.mark.external]

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


@pytest.mark.asyncio
async def test_configured_daytona_sandbox_supports_core_contract():
    if os.getenv("II_AGENT_RUN_SANDBOX_SMOKE", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set II_AGENT_RUN_SANDBOX_SMOKE=1 to run sandbox provider smoke tests")

    settings = get_settings()
    if settings.sandbox.provider != "daytona":
        pytest.skip("This smoke test validates the configured Daytona sandbox provider only")

    suffix = uuid.uuid4().hex[:8]
    sandbox = await DaytonaSandbox.create(f"smoke-daytona-{suffix}", f"smoke-session-{suffix}")
    watcher = None
    try:
        command_output = await sandbox.run_command("printf hello")
        assert command_output == "hello"

        python_output = await sandbox.run_python_code("print('python-ok')")
        assert "python-ok" in python_output

        await sandbox.write_file("/workspace/daytona-smoke.txt", "first")
        assert await sandbox.read_file("/workspace/daytona-smoke.txt") == "first"
        assert (
            await sandbox.download_file("/workspace/daytona-smoke.txt", format="bytes") == b"first"
        )

        tree, contents = await sandbox.list_files_with_contents("/workspace")
        assert tree.path == "/workspace"
        assert "/workspace/daytona-smoke.txt" in contents

        events: list[object] = []
        exits: list[Exception | None] = []
        watcher = await sandbox.watch_dir(
            "/workspace",
            on_event=events.append,
            on_exit=lambda exc: exits.append(exc),
            timeout=4,
            recursive=True,
        )
        await sandbox.write_file("/workspace/daytona-smoke.txt", "second")
        await asyncio.sleep(2)
        assert any(getattr(evt, "type", "") == "write" for evt in events)

        handle = await sandbox.create_live_terminal(
            cols=80,
            rows=24,
            cwd="/workspace",
            on_data=lambda _data: None,
            timeout=10,
        )
        await handle.send_input(b"exit\n")
        await handle.wait()

        preview_url = await sandbox.expose_port(settings.vscode_port)
        assert preview_url.startswith(("http://", "https://"))
    finally:
        if watcher is not None:
            await watcher.stop()
        await sandbox.pause()


@pytest.mark.codex_smoke
@pytest.mark.asyncio
async def test_configured_daytona_sandbox_exposes_codex_app_server_protocol():
    if os.getenv("II_AGENT_RUN_CODEX_SMOKE", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set II_AGENT_RUN_CODEX_SMOKE=1 to run Codex sandbox contract smoke tests")

    settings = get_settings()
    if settings.sandbox.provider != "daytona":
        pytest.skip("This smoke test validates the configured Daytona sandbox provider only")

    suffix = uuid.uuid4().hex[:8]
    sandbox = await DaytonaSandbox.create(
        f"smoke-daytona-codex-{suffix}",
        f"smoke-session-{suffix}",
    )
    try:
        initialize = {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "ii_agent_daytona_smoke",
                    "title": "II Agent Daytona Smoke",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        }
        script = f"""
import json
import subprocess
import sys
import time

proc = subprocess.Popen(
    ["codex", "app-server", "--listen", "stdio://"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)
assert proc.stdin is not None
assert proc.stdout is not None
proc.stdin.write({json.dumps(json.dumps(initialize))} + "\\n")
proc.stdin.flush()
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    line = proc.stdout.readline()
    if not line:
        if proc.poll() is not None:
            break
        continue
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        continue
    if payload.get("id") == 1:
        print(json.dumps(payload))
        proc.terminate()
        raise SystemExit(0)
proc.terminate()
stderr = proc.stderr.read() if proc.stderr else ""
print(json.dumps({{"error": "timeout", "stderr": stderr}}))
raise SystemExit(1)
"""
        output = await sandbox.run_command(f"python3 - <<'PY'\n{script}\nPY", timeout=30)
        response = json.loads(output.strip().splitlines()[-1])
        assert "error" not in response, response
        assert isinstance(response.get("result"), dict)
    finally:
        await sandbox.pause()
