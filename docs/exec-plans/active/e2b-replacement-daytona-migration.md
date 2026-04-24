# Replace E2B with a self-hosted Daytona sandbox provider

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

II-Agent should be able to run agent sandboxes without depending on paid E2B cloud
capacity. After this change, a developer should be able to set
`SANDBOX_PROVIDER=daytona`, run a self-hosted Daytona deployment, start an agent
session, execute commands, use live terminal flows, read and write files, expose a
preview URL, register MCP where supported, and run the Codex App Server smoke test
against the same sandbox surface used by real sessions.

The chosen replacement is Daytona for the first implementation slice. OpenSandbox
is a strong future candidate for Kubernetes-scale hardened execution, but it is not
the best first E2B replacement for this repository because the current II-Agent
contract requires live PTY behavior and Daytona documents PTY sessions directly.

## Progress

- [x] (2026-04-24) Compared OpenSandbox and Daytona using official upstream
  documentation and the current II-Agent sandbox contract.
- [x] (2026-04-24) Inspected local sandbox provider surfaces in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/`.
- [x] (2026-04-24) Selected Daytona as the first E2B replacement candidate.
- [x] (2026-04-24) Created this implementation plan with acceptance gates and
  rollback boundaries.
- [x] (2026-04-24) Implemented the Daytona provider behind the provider enum,
  config, service routing, capability matrix, and startup reporting surfaces.
- [x] (2026-04-24) Added unit coverage and opt-in smoke tests for Daytona
  provider contracts.
- [x] (2026-04-24) Validated the local Daytona OSS stack through `start.sh
  --check-only`, the live Daytona sandbox smoke, and the Codex App Server smoke
  against the Daytona sandbox image.
- [x] (2026-04-24) Made Daytona the default sandbox provider. Docker remains as
  an explicit low-level local fallback, not the default replacement for E2B.

## Surprises & Discoveries

- Observation: Docker/Podman is not an E2B replacement in the current repo; it is
  a partial local runtime. It lacks `watch_dir`, `expose_port`, `get_host`, and
  `get_mcp_client`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/docker.py`
  lines 800-833.

- Observation: The current sandbox abstraction requires more than command
  execution. It includes command execution, Python execution, live PTY, file
  operations, directory watching, port exposure, host discovery, and MCP client
  creation.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/base.py`
  lines 124-255.

- Observation: OpenSandbox is architecturally aligned with a provider contract:
  it has lifecycle and execution OpenAPI specs, Python SDKs, Docker and
  Kubernetes runtimes, command/file/code-interpreter APIs, ingress, egress, and
  secure-runtime options. The missing first-slice concern is explicit PTY parity.
  Evidence: `https://open-sandbox.ai/overview/architecture` and
  `https://github.com/alibaba/OpenSandbox`.

- Observation: Daytona has the best direct match for this repo's E2B-facing
  capabilities: Python SDK, process execution, PTY sessions over the sandbox
  process module, file system operations, preview URLs, MCP server integration,
  lifecycle operations, and OSS self-host deployment.
  Evidence: `https://www.daytona.io/docs/en/process-code-execution/`,
  `https://www.daytona.io/docs/en/pty/`,
  `https://www.daytona.io/docs/en/preview/`,
  `https://www.daytona.io/docs/en/mcp/`, and
  `https://www.daytona.io/docs/en/oss-deployment/`.

- Observation: Daytona's AGPL-3.0 license is no longer a blocking selection
  factor for this user-stated use case because this is not a product being sold.
  It remains a distribution constraint if this repository later ships modified
  Daytona code or exposes modified Daytona over a network.
  Evidence: `https://www.daytona.io/docs/en/oss-deployment/` and
  `https://github.com/daytonaio/daytona`.

- Observation: Neither Daytona nor OpenSandbox should be treated as "done"
  until file watching is proven. E2B has native `files.watch_dir`; Daytona's
  public docs expose file operations and PTY/process sessions, but not a native
  directory-watch API in the reviewed documentation.
  Evidence: local `E2BSandbox.watch_dir` in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/e2b.py`
  lines 635-652.

- Observation: The official Daytona Python SDK cannot be added directly to this
  repo today without destabilizing the dependency graph. `uv add
  daytona>=0.166.0` fails because Daytona requires `websockets>=15,<16`, while
  the existing ii-researcher/litellm chain resolves through
  `websockets>=13.1,<14`.
  Evidence: local `uv add 'daytona>=0.166.0'` resolver failure on
  2026-04-24.

- Observation: The Docker pull failure for
  `docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com`
  was a Docker Desktop/Docker Hub CDN/DNS path issue, not a Daytona product
  blocker. The local mitigation is to serialize Compose pulls and build the
  Daytona sandbox image with host networking.
  Evidence: Docker Desktop allow-list documentation identifies that R2 hostname
  as the Personal/anonymous Docker Pull/Push endpoint; Docker Compose documents
  `COMPOSE_PARALLEL_LIMIT`; Docker Buildx documents `--network host`.

- Observation: Daytona's runner hardcodes `linux/amd64` for image build/pull and
  sandbox container creation. A local Apple Silicon image tagged
  `ii-agent-codex-sandbox:local` is therefore not sufficient.
  Evidence: local Daytona runner source under `.cache/ii-agent-daytona/daytona`
  sets `Platform: "linux/amd64"` and `Architecture: "amd64"` in the Docker
  build, pull, and create paths.

- Observation: The Daytona runner's nested bridge defaults to `172.20.0.0/16`.
  If the outer Compose network uses the same subnet, the sandbox daemon can
  start but the runner cannot reliably reach the toolbox port.
  Evidence: local smoke/debug run before shifting the generated Compose network
  to `172.31.0.0/16`.

## Decision Log

- Decision: Implement Daytona first as the E2B replacement.
  Rationale: Daytona satisfies the hard PTY, process, file, preview, and MCP
  surfaces more directly than OpenSandbox. OpenSandbox is more attractive as a
  future Kubernetes/hardened-runtime substrate, but PTY uncertainty makes it a
  weaker first replacement for II-Agent's existing runtime contract.
  Date/Author: 2026-04-24 / Codex.

- Decision: Do not delete E2B or Docker/Podman in the first slice.
  Rationale: This is a provider migration, not a cleanup exercise. Daytona is
  now the default replacement for E2B after passing the live provider and Codex
  smoke tests. E2B remains an explicit fallback for users with credentials.
  Docker remains useful as a low-level local fallback and as a reference for
  current Codex App Server image checks.
  Date/Author: 2026-04-24 / Codex.

- Decision: Add provider capability gates before changing frontend behavior.
  Rationale: The repo already hit broken-workflow states when runtime capability
  assumptions leaked into UI availability. The backend must expose whether the
  configured sandbox can do PTY, preview URLs, MCP, file watch, and Codex App
  Server before workflows are enabled.
  Date/Author: 2026-04-24 / Codex.

- Decision: Implement `watch_dir` as a required Daytona validation item, not as
  a guessed native SDK call.
  Rationale: If Daytona lacks native file watching, II-Agent can provide it with
  a long-running in-sandbox watcher command over PTY/process sessions, but that
  must be tested under real event streams before claiming parity.
  Date/Author: 2026-04-24 / Codex.

- Decision: `scripts/start.sh` owns local Daytona startup when Daytona is the
  selected sandbox provider.
  Rationale: The repository startup contract is a one-stop local bootstrap. It
  should not ask the user to manually run Daytona services when the provider is
  configured for a local URL. Provider code, tests, and capability resolution
  still own the runtime contract after the service is reachable.
  Date/Author: 2026-04-24 / Codex.

- Decision: Implement Daytona through HTTP/toolbox endpoints instead of the
  official Python SDK for this slice.
  Rationale: The SDK is the nicer integration surface, but dependency
  resolution is a hard repo constraint. The direct API adapter preserves the
  Daytona provider decision without forcing a websockets/litellm dependency
  migration into this sandbox-provider task.
  Date/Author: 2026-04-24 / Codex.

## Outcomes & Retrospective

Implemented as the default provider slice. `SandboxSettings.provider` now
defaults to `daytona`, and `SANDBOX_PROVIDER=daytona` routes through
`DaytonaSandbox`, with config, secret loading, startup-managed local Daytona
bootstrap, provider capability gates, unit tests, documentation, and opt-in
smoke tests.

The live local hard gate passed on 2026-04-24 against the self-hosted Daytona
OSS stack and the Daytona-specific `linux/amd64` Codex sandbox image. Normal
test runs still collect and skip the smoke tests unless
`II_AGENT_RUN_SANDBOX_SMOKE=1` or `II_AGENT_RUN_CODEX_SMOKE=1` is set.

## Context and Orientation

Relevant local files:

- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/base.py`
  defines the sandbox provider interface.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/types.py`
  currently allows only `e2b` and `docker` provider enum values.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/core/config/sandbox.py`
  currently allows `e2b`, `docker`, and legacy `local` settings values.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py`
  resolves configured providers and creates/connects provider instances.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/e2b.py`
  is the reference capability implementation.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/docker.py`
  is a partial local provider and should not be used as the parity target.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/smoke/test_codex_app_server_contract.py`
  is the existing Codex App Server smoke-test surface and should be generalized.
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/core/runtime_capabilities.py`
  already starts the capability-gating direction and should be extended rather
  than bypassed.

Definitions:

- Provider contract: the `Sandbox` abstract interface that every provider must
  implement for II-Agent.
- Runtime capability: backend-owned truth about whether a configured sandbox can
  support workflow features such as Plan UI, PTY, preview URLs, MCP, and Codex
  App Server.
- Daytona control plane: self-hosted Daytona API, proxy, runner, SSH gateway,
  database, Redis, registry, and object storage as described by Daytona OSS
  deployment docs.

Research basis:

- OpenSandbox official docs: protocol-first sandbox platform with SDK, specs,
  Docker/Kubernetes runtimes, command/files/code interpreter, ingress, egress,
  and secure runtime options.
  Source: `https://open-sandbox.ai/overview/architecture`
- OpenSandbox GitHub: Apache-2.0, Python SDK, CLI, MCP server, Docker local
  server, Kubernetes examples, Codex CLI example.
  Source: `https://github.com/alibaba/OpenSandbox`
- OpenSandbox secure runtime guide: gVisor, Kata, and Firecracker runtime
  support through server-level configuration.
  Source: `https://github.com/alibaba/OpenSandbox/blob/main/docs/secure-container.md`
- Daytona OSS deployment: Docker Compose self-host path, AGPL-3.0, API, proxy,
  runner, SSH gateway, PostgreSQL, Redis, registry, MinIO, and supporting
  services.
  Source: `https://www.daytona.io/docs/en/oss-deployment/`
- Daytona architecture: SDK/CLI/dashboard/MCP/SSH interface plane, control
  plane, proxy, sandbox manager, compute runners, and sandbox daemon.
  Source: `https://www.daytona.io/docs/en/architecture/`
- Daytona process and code execution: command execution, stateful code
  interpreter, sessions, command input, and logs.
  Source: `https://www.daytona.io/docs/en/process-code-execution/`
- Daytona PTY: explicit create/connect/list/kill/resize PTY session support.
  Source: `https://www.daytona.io/docs/en/pty/`
- Daytona preview URLs: generated URLs for services running inside sandboxes.
  Source: `https://www.daytona.io/docs/en/preview/`
- Daytona MCP: MCP server exposes sandbox management, filesystem, git, process,
  code execution, computer use, and preview tools.
  Source: `https://www.daytona.io/docs/en/mcp/`

## Plan of Work

### Phase 0: Provider contract hardening

1. Add a provider-capability model for sandbox-specific capabilities if the
   existing runtime capability layer is too Codex-focused.
   - Include `commands`, `python_code`, `pty`, `files`, `file_watch`,
     `preview_url`, `host_discovery`, `mcp`, `pause_resume`, `codex_app_server`.
   - Keep capabilities additive and backend-owned.

2. Add contract tests that run against a fake provider and, later, real provider
   smoke fixtures:
   - create/connect/delete lifecycle,
   - command execution,
   - live PTY echo/input,
   - read/write/list/download file operations,
   - `watch_dir` event delivery,
   - preview URL for a simple HTTP server,
   - MCP client creation,
   - Codex App Server initialize.

3. Update existing Docker/E2B tests only as needed to express the same provider
   contract without changing their behavior.

### Phase 1: Daytona provider configuration

1. Add `DAYTONA` to `SandboxProviderType`.

2. Extend `SandboxProvider` in
   `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/core/config/sandbox.py`
   to include `"daytona"`.

3. Add settings:
   - `SANDBOX_DAYTONA_API_URL`
   - `SANDBOX_DAYTONA_API_KEY`
   - `SANDBOX_DAYTONA_TARGET`
   - `SANDBOX_DAYTONA_DEFAULT_IMAGE` or snapshot reference
   - `SANDBOX_DAYTONA_AUTO_STOP_INTERVAL`
   - `SANDBOX_DAYTONA_EPHEMERAL`
   - `SANDBOX_DAYTONA_PUBLIC_PREVIEW`
   - `SANDBOX_DAYTONA_NETWORK_BLOCK_ALL`
   - optional `SANDBOX_DAYTONA_NETWORK_ALLOW_LIST`

4. Do not add the `daytona` Python SDK to the main dependency set until the
   `websockets` conflict with the current ii-researcher/litellm chain is
   resolved. Use Daytona HTTP/toolbox APIs directly for this slice.

5. Update `.env.example` with a self-hosted Daytona block and keep E2B/Docker
   examples visible as alternatives.

### Phase 2: DaytonaSandbox adapter

Create
`/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/daytona.py`
with the same public behavior as `E2BSandbox`:

1. Lifecycle:
   - create sandbox from configured image/snapshot,
   - attach II-Agent metadata,
   - set timeout/auto-stop/ephemeral behavior,
   - connect to existing sandbox by `provider_sandbox_id`,
   - map Daytona states into `SandboxStatus`,
   - delete/stop/archive according to existing service semantics.

2. Commands:
   - implement `run_command` through Daytona process execution,
   - preserve timeout/cwd/env semantics,
   - return stdout-compatible strings,
   - include exit-code and stderr context in `SandboxOperationError`.

3. Python code:
   - use Daytona code interpreter or process execution consistently,
   - decide whether stateful Python is required for parity.

4. PTY:
   - implement `create_live_terminal` with Daytona PTY create/connect APIs,
   - translate callbacks into `TerminalDataCallback`,
   - support resize/stop/kill through a `DaytonaLiveTerminalHandle`.

5. Files:
   - map read/write/upload/download/delete/list/content helpers to Daytona file
     system APIs.
   - preserve language detection and binary/large-file behavior locally where
     Daytona metadata does not match E2B metadata.

6. File watching:
   - first attempt native SDK support only if verified in the installed SDK.
   - otherwise run a polling watcher over the Daytona toolbox filesystem API
     and map events into the existing callback shape.
   - treat this as a hard smoke-test gate.

7. Preview/host/MCP:
   - implement `expose_port` through Daytona preview URL support.
   - implement `get_host` using the preview/proxy host semantics available from
     Daytona.
   - implement `get_mcp_client` only if the session sandbox exposes the same
     in-sandbox MCP endpoint expected by II-Agent; otherwise capability-gate MCP
     off and do not fake success.

### Phase 3: Service integration

1. Update provider resolution in
   `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py`
   so `SANDBOX_PROVIDER=daytona` creates and connects `DaytonaSandbox`.

2. Update repository tests in
   `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/engine/test_sandbox_service.py`
   to cover Daytona create/connect routing.

3. Update session fork behavior only if Daytona has copy/fork/archive semantics
   that can safely preserve shared sandbox state. If not, session fork should
   degrade to "new sandbox required" for Daytona until validated.

4. Update project design proxy validation if it currently hardcodes E2B host
   patterns.

### Phase 4: Startup and smoke validation

1. Extend `scripts/start_preflight.py` to report Daytona config truth:
   - API URL set,
   - API key set when required,
   - SDK importable,
   - self-host URL reachable in check-only mode,
   - clear warning if Daytona is not running.

2. Extend `scripts/start.sh` to auto-start local Daytona when
   `SANDBOX_PROVIDER=daytona` points at localhost and the API is unavailable:
   - clone Daytona OSS into a repo-local cache when missing,
   - generate a Docker Compose file with non-conflicting host ports,
   - retry Docker Compose startup and limit Compose parallelism for transient
     Docker Hub/Cloudflare image pull failures,
   - export the effective `SANDBOX_DAYTONA_API_URL`,
   - wait for the Daytona API probe to pass,
   - keep Codex workflow capabilities disabled unless smoke verification passes.

3. Generalize `src/tests/smoke/test_codex_app_server_contract.py` from
   Docker-only to provider-contract smoke tests:
   - Daytona sandbox creation,
   - `codex app-server` starts inside the Daytona sandbox image,
   - JSON-RPC `initialize` with `experimentalApi` succeeds,
   - dynamic tool call round trip succeeds,
   - approval/user-input shapes remain compatible.

4. Add `uv run pytest -m sandbox_smoke` for provider-independent smoke tests,
   and `uv run pytest -m codex_smoke` for Codex App Server protocol validation.

### Phase 5: Documentation and rollout

1. Add a short self-host Daytona setup doc under
   `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/docs/`.

2. Update sandbox provider references in
   `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/docs/CODEMAPS/dependencies.md`
   and any product docs that still say E2B is the only production sandbox.

3. Default local development can remain Docker until Daytona smoke is easy to
   run locally. Do not change defaults until a clean Daytona setup path exists.

4. After smoke tests pass, decide whether to:
   - keep Docker as a lightweight provider,
   - demote Docker to Codex-image test fixture only,
   - or remove Docker after one compatibility window.

## Validation and Acceptance

Behavioral acceptance:

1. With `SANDBOX_PROVIDER=daytona`, II-Agent can create a sandbox and persist an
   `agent_sandboxes` record with provider `daytona`.

2. Reconnecting to an existing Daytona sandbox works after server restart.

3. Shell tools can create a session, send stdin, receive output, resize/stop the
   terminal, and recover cleanly when the PTY disappears.

4. File tools can write, read, upload, download, delete, list, and inspect text,
   binary, image, and too-large files with the same response semantics as E2B.

5. `register_port` returns a reachable preview URL for a simple in-sandbox HTTP
   server.

6. Project secret/env sync writes `.env` and `/app/.user_env.sh` into the
   Daytona sandbox before a paused run resumes.

7. File watching delivers create/update/delete events or the backend explicitly
   disables dependent features and surfaces a truthful capability gap.

8. Codex App Server Plan/resume workflows stay disabled until the Daytona image
   passes the App Server smoke test.

Required commands:

```bash
uv run ruff check --fix-only <changed_python_files>
uv run ruff format <changed_python_files>
uv run ruff check <changed_python_files>
uv run ruff format --check <changed_python_files>
uv run pytest src/tests/unit/engine/test_sandbox_service.py
uv run pytest src/tests/unit/engine/test_daytona_sandbox.py
uv run pytest src/tests/unit/core/test_runtime_capabilities.py
uv run pytest src/tests/unit/projects/test_sandbox_env_sync_service.py
uv run pytest src/tests/smoke/test_daytona_sandbox_contract.py
uv run pytest -m sandbox_smoke src/tests/smoke/test_daytona_sandbox_contract.py
uv run pytest -m codex_smoke src/tests/smoke/test_daytona_sandbox_contract.py src/tests/smoke/test_codex_app_server_contract.py
git diff --check
```

Expected outputs:

- Ruff commands pass with no reported violations.
- Unit tests pass.
- With smoke env vars unset, the targeted smoke files collect and skip cleanly.
- With `II_AGENT_RUN_SANDBOX_SMOKE=1`, `sandbox_smoke` creates and destroys a
  real Daytona sandbox.
- With `II_AGENT_RUN_CODEX_SMOKE=1`, `codex_smoke` proves the configured
  Daytona sandbox image supports the pinned `codex app-server` protocol.
- `git diff --check` reports no whitespace errors.

Current local caveat: `uv run pytest -m sandbox_smoke` is not a reliable global
gate yet because this repo has unrelated stale test modules that fail during
collection before marker filtering can run. Keep the release gate targeted to the
smoke files above until those legacy collection failures are fixed.

## Idempotence and Recovery

- Provider additions are additive. If Daytona fails, set `SANDBOX_PROVIDER=e2b`
  or `SANDBOX_PROVIDER=docker` and the old provider routes should still work.
- Keep E2B code untouched except for shared tests/capability interfaces.
- Keep Docker code untouched except for shared tests/capability interfaces.
- Daytona sandbox cleanup must be best-effort and safe to rerun. Every smoke
  test must tag sandboxes with II-Agent metadata and attempt cleanup by ID.
- If a Daytona sandbox is created but DB persistence fails, cleanup the Daytona
  sandbox before surfacing the error.
- If DB persistence succeeds but Daytona creation fails, mark the sandbox record
  `ERROR` with provider error metadata and do not claim the run is ready.
- If file watching cannot be made reliable, ship Daytona as a degraded provider
  only if all workflows depending on file-watch truth are capability-gated.

## Critical Review

The main risk is over-trusting Daytona's breadth. Daytona clearly has stronger
first-slice parity than OpenSandbox, but this plan still has two non-negotiable
unknowns: directory watching and self-host operational friction. If either fails,
the correct move is not to rationalize partial parity. The provider should remain
behind capability gates until those gaps are proven or explicitly disabled.

The second risk is turning the migration into a broad runtime redesign. The
smallest correct implementation is a new provider adapter plus capability tests.
Runtime profile cleanup, Docker removal, and provider-default changes should wait
until the adapter is proven.
