# Daytona sandbox provider

II-Agent defaults to the self-hosted Daytona sandbox provider. The relevant
settings are:

```bash
SANDBOX_PROVIDER=daytona
SANDBOX_DAYTONA_API_URL=http://localhost:3980/api
SANDBOX_DAYTONA_API_KEY=<admin-or-api-key-if-required>
SANDBOX_DAYTONA_DEFAULT_IMAGE=registry:6000/ii-agent-codex-sandbox:daytona-amd64
```

Use `SANDBOX_DAYTONA_SNAPSHOT` instead of `SANDBOX_DAYTONA_DEFAULT_IMAGE` when
you have a prebuilt Daytona snapshot. The provider creates sandboxes from the
configured image/snapshot, attaches II-Agent labels, executes commands through
the Daytona toolbox API, exposes preview URLs, and uses a polling watcher for
workspace file-change events.

`./scripts/start.sh` owns local Daytona startup. If `SANDBOX_PROVIDER=daytona`
points at a local URL and the API is not reachable, the script clones the
Daytona OSS repository into `.cache/ii-agent-daytona/`, generates a compose file
with non-conflicting host ports, starts the Daytona stack with Docker Compose,
and exports the effective `SANDBOX_DAYTONA_API_URL` before launching II-Agent.
The default II-Agent local Daytona API port is `3980` to avoid the common
`localhost:3000` development-app collision.
For the local OSS stack, `start.sh` also serializes Compose pulls, uses a
non-overlapping Daytona outer bridge subnet, builds a Daytona-specific
`linux/amd64` sandbox image, pushes it to Daytona's local registry, and persists
the runner-visible image reference in `.env`.

Override generated local ports only when needed:

```bash
II_AGENT_DAYTONA_API_PORT=3980
II_AGENT_DAYTONA_PROXY_PORT=3981
II_AGENT_DAYTONA_REPO_DIR=/path/to/daytona
II_AGENT_DAYTONA_COMPOSE_ATTEMPTS=3
II_AGENT_DAYTONA_COMPOSE_PARALLEL_LIMIT=1
II_AGENT_DAYTONA_OUTER_NETWORK_SUBNET=172.31.0.0/16
II_AGENT_DAYTONA_SANDBOX_DOCKERFILE=docker/sandbox/daytona.Dockerfile
```

## Dependency note

The official Daytona Python SDK is not a direct project dependency yet. Current
Daytona SDK releases require `websockets>=15,<16`, while this repo's existing
ii-researcher/litellm dependency chain resolves to `websockets>=13.1,<14`.
`uv add daytona>=0.166.0` fails for that reason. The provider therefore uses
Daytona's HTTP and toolbox endpoints with the repo's existing `httpx` and
`websockets` dependencies.

## Validation

Run normal preflight:

```bash
./scripts/start.sh --check-only
```

For a Daytona-backed local run, use the normal one-stop startup path:

```bash
./scripts/start.sh
```

Run the live sandbox smoke test only when a Daytona server is available:

```bash
II_AGENT_RUN_SANDBOX_SMOKE=1 SANDBOX_PROVIDER=daytona \
  uv run pytest -m sandbox_smoke src/tests/smoke/test_daytona_sandbox_contract.py
```

Run the Codex App Server protocol smoke test only when the configured
Daytona image or snapshot includes the pinned OpenAI Codex CLI:

```bash
II_AGENT_RUN_CODEX_SMOKE=1 SANDBOX_PROVIDER=daytona \
  uv run pytest -m codex_smoke src/tests/smoke/test_daytona_sandbox_contract.py
```

Do not enable `CODEX_APP_SERVER_SMOKE_VERIFIED=true` for Daytona until the
Codex smoke test passes against the actual runtime image or snapshot.
