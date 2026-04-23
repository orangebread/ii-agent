# Production Hardening For AI Runtime Workflows

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

After this effort, a user should be able to use AI-backed flows in this application
without tripping over hidden runtime-contract mismatches, secret propagation gaps,
or resume-path drift. The application needs to stop pretending that stored config,
runtime files, and provider request contracts are all the same thing. They are not.

Observable outcomes after implementation:

- Saving secrets through the active frontend flow actually materializes runtime env
  files for the live sandbox before the paused run resumes.
- `DATABASE_URL` saves do not crash, and the env-sync path uses a single canonical
  database source instead of stale project JSON.
- Human-in-the-loop resumes recreate the same effective agent capability surface that
  the initial run used, rather than silently dropping `tool_args`.
- OpenAI/Codex request shaping is validated across both agent and chat execution
  surfaces, with Codex-specific constraints handled in one place instead of by drift.
- The test suite exercises the real streaming/request seams that have been failing in
  production, not stale or mocked-adjacent code paths.
- Dead or misleading paths (`SAVE_ENV`, unused media prompt additions, flattened
  realtime errors) are either fixed or removed so the system has one truth per behavior.

## Progress

- [x] (2026-04-22 16:08Z) Revalidated the previously surfaced findings against the current code before writing this plan.
- [x] (2026-04-22 16:08Z) Confirmed there is no active Taskplane state in this repo; ExecPlan is the active orchestration document for this effort.
- [x] (2026-04-22 16:08Z) Drafted this ExecPlan with phased workstreams, validation gates, and explicit acceptance criteria.
- [x] (2026-04-22 16:30Z) Implemented Phase 1 for the active secrets route: real sandbox env sync, canonical `DATABASE_URL` lookup, route regression tests, and env-sync service tests.
- [x] (2026-04-22 17:15Z) Hardened the Phase 1 env-sync contract after adversarial review: backend validation now rejects invalid env-var names, sync skips legacy invalid keys safely, project paths are workspace-bounded, and secret sync provisions a sandbox when needed.
- [x] (2026-04-22 21:20Z) Investigated the residual-risk layer and promoted the next stage from "patch remaining bugs" to a contract redesign: secret persistence, runtime materialization, paused-run resume, and provider verification now have an explicit unified strategy.
- [x] (2026-04-22 23:35Z) Implemented the Phase 2 contract shift: `ask_user_env` now persists and syncs secrets through backend tool execution on `CONTINUE_RUN`, the frontend no longer calls the project secrets REST route for paused-run secret submission, and the dead `SAVE_ENV` command has been removed from the active protocol surface.
- [x] (2026-04-22 16:45Z) Implemented the first Phase 3 slice: `continue_run` now reuses original run-task `tool_args` and `metadata` when recreating the agent, with focused regression coverage.
- [x] (2026-04-22 23:35Z) Implemented the Phase 3 secret-route semantics: project-panel secret routes now persist first and only best-effort sync to already-existing sandboxes without provisioning runtime infrastructure as a settings side effect.
- [ ] Implement Phase 4: add sandbox secret revision tracking and reconcile runtime env state on sandbox init/resume instead of relying on lucky ordering.
- [x] (2026-04-22 23:35Z) Implemented the Phase 5 consolidation slice: `add_user_env`, database/init helpers, and the raw session-project secret setter now flow through validated/encrypted secret services or the new orchestrator instead of mutating plaintext secret JSON directly.
- [ ] Execute the Codex chat validation gate and unify request-shaping behavior across agent/chat OpenAI Responses surfaces.
- [ ] Fix false-confidence tests, add end-to-end contract coverage, and run the release verification set.

## Surprises & Discoveries

- Observation: the live frontend `ask_user_env` flow does not use the websocket `SAVE_ENV` command at all; it saves through the project secrets REST route and only then emits `CONTINUE_RUN`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/secrets-input.tsx` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/tool-confirmation.tsx`

- Observation: the project secrets route claims to sync env files, but its injected `SandboxEnvSyncService` is a no-op stub.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/dependencies.py`

- Observation: the active route has a concrete crash when `DATABASE_URL` is present because it references `session_uuid`, which is undefined.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py`

- Observation: the POST secrets route uses `project.database_json` for sync, even though `DATABASE_URL` writes now land in `ProjectDatabase` rows. The route can therefore sync stale or empty data after a successful write.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/databases/service.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py`

- Observation: the alternate `SAVE_ENV` handler is not just unused; it calls a nonexistent `add_secrets_and_sync` method and reconstructs the agent with unsupported factory kwargs.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/save_env.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py`

- Observation: `continue_run` rebuilds an agent without the `tool_args` that the initial query path supplied, so resumed runs can have a different tool surface than the run that paused.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`

- Observation: the implemented env-sync service intentionally syncs only to an existing sandbox. It does not auto-provision one when secrets are edited outside a live run.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/env_sync_service.py`
- Observation: the secrets route and UI are explicitly framed as environment-variable management, not arbitrary secret-vault storage, so enforcing env-var name validation at the backend is aligned with the product contract.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/project/project-panel.tsx` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/secrets-input.tsx`

- Observation: the provider-policy duplication between agent and chat OpenAI/Codex stacks is real, but the exact Codex chat `store=false` failure is still an inference until validated against the live chat path.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/models/openai/responses.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/openai.py`

- Observation: the chat OpenAI deep tests are patching `responses.stream`, but the implementation streams via `responses.create`, so part of the critical request path is effectively untested.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/openai.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/chat/test_chat_llm_openai_deep.py`

- Observation: the active `ask_user_env` path drops the tool's authoritative `project_directory`. The tool requires it, but the frontend saves through a generic session-scoped REST route and then resumes separately, so sync falls back to `project.project_path`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/dev/ask_user_env.py`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/secrets-input.tsx`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/tool-confirmation.tsx`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py`

- Observation: the secrets routes still perform sandbox side effects before the request-scoped database session commits, so DB truth and runtime truth can diverge on partial failure.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/core/db/base.py`

- Observation: `add_user_env` reports `synced_to_sandbox=True`, but it only persists to the database and never calls the env-sync service.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/dev/add_user_env.py`

- Observation: multiple non-router paths still mutate `project.secrets_json` directly, bypassing encryption discipline, validation, and canonical `DATABASE_URL` handling.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/dev/init_tool.py`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/dev/database.py`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/service.py`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/utils.py`

- Observation: env-var validation currently lives at the REST schema edge, not the domain boundary, so internal writers can still persist invalid keys even though sync will later skip them.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/schemas.py`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/service.py`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/dev/add_user_env.py`

- Observation: the project-panel settings UI uses the same session-scoped secrets routes as the paused-run `ask_user_env` flow, so a generic settings edit currently provisions infrastructure as a side effect.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/project/project-panel.tsx`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py`

- Observation: this work is being done in a dirty worktree with unrelated changes already present in OAuth/runtime files. The hardening work should avoid those surfaces until the scoped critical fixes are merged or explicitly coordinated.
  Evidence: `git status --short` in `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent`

- Observation: strict env-name validation on writes is necessary, but strict validation on delete is operationally wrong because it prevents cleanup of legacy invalid keys already persisted by older code paths.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/schemas.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/service.py`

## Decision Log

- Decision: Phase 1 starts with the active env-secret path rather than with broader provider refactors.
  Rationale: the system is currently lying about a core runtime guarantee. Users can provide secrets and resume a run while the backend never materializes them into the sandbox.
  Date/Author: 2026-04-22 / Codex

- Decision: the first implementation slice should stay off the dirty OAuth/runtime files already modified in the worktree.
  Rationale: mixing cross-cutting provider refactors with the urgent env-sync fix would make review harder and raise merge/conflict risk for no immediate user benefit.
  Date/Author: 2026-04-22 / Codex

- Decision: the Codex chat `store` question is a validation gate, not a planning blocker.
  Rationale: the system already has enough confirmed defects to justify a full remediation plan. The remaining uncertainty only changes the urgency and shape of the shared request-shaping refactor.
  Date/Author: 2026-04-22 / Codex

- Decision: env-file sync must be idempotent and must preserve unrelated project env content.
  Rationale: blindly overwriting `.env` is process theater disguised as a fix. The system needs a bounded managed section so deletes and updates are safe.
  Date/Author: 2026-04-22 / Codex

- Decision: the env-sync service should skip cleanly when no sandbox exists instead of provisioning a sandbox as a side effect of secret editing.
  Rationale: this was the original implementation decision, but it did not survive adversarial review because it left the `ask_user_env` workflow conditionally broken.
  Date/Author: 2026-04-22 / Codex

- Decision: the env-sync service now provisions or reconnects the session sandbox during secret sync.
  Rationale: the product contract requires runtime env materialization before the paused AI workflow resumes. The previous “skip if missing” behavior was architecturally cleaner and operationally wrong.
  Date/Author: 2026-04-22 / Codex

- Decision: secret handling now needs a single backend-owned orchestration boundary instead of more route-level patches.
  Rationale: secret persistence, runtime materialization, paused-run resume, and database canonicalization are currently split across incompatible entry points. Keeping them split is how the same class of bugs keeps recurring.
  Date/Author: 2026-04-22 / Codex

- Decision: the active `ask_user_env` flow should move into `CONTINUE_RUN`, not into a repaired `SAVE_ENV` command and not continue through the generic project secrets REST route.
  Rationale: the frontend already uses `CONTINUE_RUN`, and the backend already has authoritative paused-run context there. That is the right place to recover the tool's `project_directory`, persist secrets, sync runtime env state, and only then resume execution.
  Date/Author: 2026-04-22 / Codex

- Decision: project settings routes should default to persist-only behavior and must not provision a sandbox as a side effect of editing settings.
  Rationale: a settings panel is not an execution path. Provisioning runtime infrastructure from a generic edit route is expensive, surprising, and conflates "save config" with "apply to live runtime."
  Date/Author: 2026-04-22 / Codex

- Decision: runtime env synchronization must become revision-based.
  Rationale: syncing "because a route happened to run" is not reliable enough. The sandbox needs to know whether its env state is stale relative to persisted secret state so new or resumed runtimes can reconcile deterministically.
  Date/Author: 2026-04-22 / Codex

- Decision: `DATABASE_URL` should be treated as canonical project-database state, with secret/env views derived from that source rather than duplicated writes spread across tools.
  Rationale: the current duplication between `ProjectDatabase` records and `project.secrets_json` is already causing drift and stale sync behavior. One source of truth is mandatory here.
  Date/Author: 2026-04-22 / Codex

- Decision: legacy invalid secret keys should be purged opportunistically during future valid mutations, and delete operations must remain permissive enough to clean up old bad data.
  Rationale: rejecting invalid keys on write is correct, but trapping already-corrupted state behind the same validation is just self-inflicted operability failure.
  Date/Author: 2026-04-22 / Codex

## Outcomes & Retrospective

Partially complete.

Implemented in the first slice:

- The project secrets route now uses a real `SandboxEnvSyncService` at `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/env_sync_service.py` instead of the DI no-op placeholder.
- The live secrets flow now writes managed env content into `<project_path>/.env` and `/app/.user_env.sh` for active sandboxes without clobbering unrelated file content.
- The POST secrets route no longer crashes on `DATABASE_URL`.
- The secrets router now uses canonical database lookup through `DatabaseService.get_project_db_connection(...)` after each mutation instead of stale `project.database_json`.
- Targeted tests now cover the previously untested POST `DATABASE_URL` branch and the env-sync managed-block behavior.

Remaining gaps after the first slice will likely include:

- the dead `SAVE_ENV` websocket path,
- broader resume-path drift beyond the recovered `tool_args`/`metadata` slice if more runtime state turns out to matter,
- provider request-shaping duplication,
- stale tests on chat streaming,
- low-fidelity error propagation in realtime handlers.

After the redesign slice, the secrets workflow now has a real contract boundary in `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/orchestrator.py`. Paused-run `ask_user_env` submission now stays on `CONTINUE_RUN`, persists and syncs through backend execution, and no longer depends on a separate REST save step. Project settings edits no longer provision sandboxes, and the dead `SAVE_ENV` path is removed from the active command surface.

The remaining gap is no longer basic secret propagation. It is deterministic reconciliation and provider parity:

- sandbox secret revision tracking is still missing,
- Codex/OpenAI chat-vs-agent request-shaping still needs live validation and consolidation,
- realtime error reporting is still flatter than it should be for production operations.

## Context and Orientation

This plan spans the project secrets workflow, the realtime resume workflow, and the
provider request layers. The key files are:

- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/dependencies.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/router.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/service.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/secrets/orchestrator.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/projects/databases/service.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/secrets-input.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent/tool-confirmation.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/models/openai/responses.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/openai.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/projects/test_project_router_coverage.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/realtime/test_socket_handlers_r4.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/chat/test_chat_llm_openai_deep.py`

Definitions used here:

- Active secrets flow: the user-facing path triggered by `ask_user_env`, where the frontend submits the provided secret values through `CONTINUE_RUN` and the resumed backend tool execution persists and syncs them before continuing.
- Managed env block: a clearly delimited section inside `.env` and `/app/.user_env.sh` that II-Agent owns, so it can update and delete managed keys without destroying unrelated content.
- Resume-path drift: a paused run is resumed with a different effective runtime configuration than the one that produced the pause.
- Provider contract drift: agent and chat stacks talk to the same backend with different request shapes and assumptions.
- Secret orchestrator: a backend service that owns validation, canonical persistence, runtime env materialization, and sync-status bookkeeping for project secrets.
- Secret revision: a monotonic version or content hash representing the latest persisted secret state that runtime sandboxes can compare against their last synced state.

## Plan of Work

### Cross-layer target architecture

This effort needs one coherent contract, not three partially overlapping ones.

The target contract is:

1. Persisted secret state is authoritative and validated in one backend service.
2. Runtime env files are a materialized view of persisted state plus canonical derived
   values like `DATABASE_URL`.
3. The paused-run `ask_user_env` flow is a backend-owned orchestration step:
   persist -> commit -> sync runtime -> resume.
4. Generic settings edits do not provision runtime infrastructure; they only persist,
   then either:
   - mark runtime env state stale for later reconciliation, or
   - best-effort sync to an already existing sandbox without provisioning one.
5. New or resumed sandboxes reconcile env state by comparing their last synced revision
   to the latest persisted secret revision.

### Phase 1: Fix the live secrets path

1. Replace the placeholder `SandboxEnvSyncService` dependency with a real service that:
   - connects to the active sandbox when one exists for the session,
   - writes or updates a managed secrets block in `<project_path>/.env` when `project_path` is available,
   - writes or updates a managed shell-export block in `/app/.user_env.sh`,
   - is idempotent and preserves unrelated file content,
   - tolerates missing sandboxes without crashing unrelated secret persistence.

2. Update the secrets router so all secret mutations compute `database_url` from the
   `DatabaseService` canonical source after mutation, not from stale `project.database_json`.

3. Fix the concrete POST `DATABASE_URL` crash by replacing `session_uuid` with `session_id`.

4. Add regression tests for:
   - POST secrets with plain API key,
   - POST secrets with `DATABASE_URL`,
   - replace/delete sync behavior using canonical database lookup,
   - env-sync service behavior for create/update/delete semantics inside managed blocks.

### Phase 2: Replace split authority in env handling

1. Introduce a canonical secret orchestration service in the backend. It should own:
   - env-var name validation and normalization,
   - encrypted project-secret persistence,
   - canonical `DATABASE_URL` lookup and projection,
   - runtime env materialization into `.env` and `/app/.user_env.sh`,
   - sync status / revision bookkeeping.

2. Rewire the active `ask_user_env` flow to use `CONTINUE_RUN` as the only frontend
   command for secret submission:
   - the frontend sends secret values as `user_input`,
   - the backend loads the paused tool requirement,
   - the backend extracts authoritative `project_directory` from paused tool state,
   - the backend persists and syncs secrets before resuming the run.

3. Delete `SAVE_ENV` after the new `CONTINUE_RUN` branch is live.
   - If backward compatibility is required, keep a thin adapter that delegates into the
     same orchestration service, then deprecate it explicitly.

4. Update the ask-user UI copy so it no longer implies a separate generic save path.

### Phase 3: Separate settings persistence from runtime execution

1. Change the project secrets REST routes to persist-only by default.
2. For settings-driven secret edits:
   - do not call `get_sandbox_by_session(...)`,
   - optionally sync only to an existing sandbox via `get_sandbox_for_session(...)`,
   - otherwise mark runtime env state stale and let sandbox init/reconnect reconcile it.
3. Preserve the Phase 3 resume-integrity work already done for `tool_args`/`metadata`,
   but extend it to ensure the new ask-user secret path uses the same run context.

### Phase 4: Add revision-based runtime reconciliation

1. Add a dedicated secret revision or stable content hash.
2. Store the last synced revision and target project path in sandbox/provider state.
3. On sandbox init or reconnect:
   - compare current persisted revision to last synced revision,
   - materialize runtime env state if stale,
   - update sync metadata after success.
4. Use the same reconciliation on paused-run resume so resumed runs do not depend on
   whether a settings route or prior sync happened "recently enough."

### Phase 5: Migrate alternate secret writers and remove drift

1. Move `add_user_env` onto the orchestrator so it either truly syncs runtime env files
   or stops claiming it does.
2. Replace direct `project.secrets_json` mutations in init/database helpers with calls
   into the orchestrator or `SecretService`.
3. Delete or neuter `ProjectService.update_session_project_secrets(...)` so raw plaintext
   writes are not a supported path.
4. Tighten domain-level validation so invalid env names are rejected no matter which
   entry point is used.
5. Medium-term: stop persisting `DATABASE_URL` redundantly in `project.secrets_json` and
   synthesize it from the project database domain when building env materialization views.

### Phase 6: Unify OpenAI/Codex request shaping

1. Run the validation gate: confirm whether Codex-backed chat requires the same
   stateless `store=false` semantics as the agent runtime.
2. Extract shared request-shaping logic or a shared contract helper so chat and agent
   surfaces do not diverge on:
   - `instructions`,
   - `store`,
   - `previous_response_id`,
   - reasoning-specific includes.
3. Expand tests so they patch the actual SDK seam (`responses.create`) and assert the
   built request parameters directly.

### Phase 7: Verification, observability, and operational hardening

1. Add backend integration coverage for:
   - paused `ask_user_env` -> submit secrets -> runtime sync -> resume,
   - sync failure after persistence but before resume,
   - settings-panel secret edit that does not provision a sandbox,
   - sandbox init reconciliation when secret revision is stale.
2. Fix false-confidence chat provider tests so they assert the real `responses.create(...)`
   request seam.
3. Improve realtime error propagation:
   - do not flatten actionable provider/configuration failures into generic "Error processing message",
   - preserve user-fixable messages for secrets/runtime/provider issues.
4. Either wire `system_prompt_addition` through the chat flow or remove it so dead
   behavior is not left pretending to exist.
5. Add one release-gate smoke path against a real OAuth-backed provider configuration
   before calling this hardening effort complete.

## Validation and Acceptance

### Acceptance Criteria

- When the user submits secrets during an `ask_user_env` pause, the frontend sends one
  resume action and the backend owns the full sequence: persist -> commit -> sync runtime
  env -> resume agent.
- The active `ask_user_env` flow uses the paused tool's authoritative `project_directory`,
  not a fallback generic project path.
- Saving `DATABASE_URL` through the POST secrets route no longer raises a server error.
- `DATABASE_URL` env materialization comes from one canonical database source rather than
  duplicated stale state.
- A paused run resumed after secret entry or other user input preserves the original
  agent tool surface.
- Project-panel secret edits do not provision a sandbox as a side effect.
- New or resumed sandboxes reconcile stale secret/env state based on a revision check
  rather than assuming the latest route call already handled it.
- Codex/OpenAI request-shaping rules are proven by tests at the actual execution seam.
- No supported path can persist plaintext secret payloads or bypass env-var validation.

### Validation Commands

Phase 1 validation:

```bash
cd /Volumes/OWC\ Envoy\ Ultra/projects/_tools_/ii-agent
uv run pytest src/tests/unit/projects/test_project_router_coverage.py
uv run pytest src/tests/unit/projects/test_sandbox_env_sync_service.py
uv run ruff check --fix-only src/ii_agent/projects/dependencies.py src/ii_agent/projects/secrets/router.py src/ii_agent/projects/secrets/service.py src/ii_agent/projects/secrets/env_sync_service.py src/tests/unit/projects/test_project_router_coverage.py src/tests/unit/projects/test_sandbox_env_sync_service.py
uv run ruff format src/ii_agent/projects/dependencies.py src/ii_agent/projects/secrets/router.py src/ii_agent/projects/secrets/service.py src/ii_agent/projects/secrets/env_sync_service.py src/tests/unit/projects/test_project_router_coverage.py src/tests/unit/projects/test_sandbox_env_sync_service.py
uv run ruff check src/ii_agent/projects/dependencies.py src/ii_agent/projects/secrets/router.py src/ii_agent/projects/secrets/service.py src/ii_agent/projects/secrets/env_sync_service.py src/tests/unit/projects/test_project_router_coverage.py src/tests/unit/projects/test_sandbox_env_sync_service.py
uv run ruff format --check src/ii_agent/projects/dependencies.py src/ii_agent/projects/secrets/router.py src/ii_agent/projects/secrets/service.py src/ii_agent/projects/secrets/env_sync_service.py src/tests/unit/projects/test_project_router_coverage.py src/tests/unit/projects/test_sandbox_env_sync_service.py
```

Later-phase validation additions:

```bash
cd /Volumes/OWC\ Envoy\ Ultra/projects/_tools_/ii-agent
uv run pytest src/tests/unit/realtime/test_socket_handlers_r4.py -k continue_run
uv run pytest src/tests/unit/realtime -k "ask_user_env or continue_run or save_env"
uv run pytest src/tests/unit/chat/test_chat_llm_openai_deep.py
uv run pytest src/tests/unit/engine/test_v1_models_openai_responses.py
uv run pytest src/tests/unit/projects/test_secret_service.py src/tests/unit/projects/test_database_source_of_truth.py
cd frontend && npm run lint && npm run build
```

## Idempotence and Recovery

- The env sync service must rewrite only its managed block, so rerunning sync with the
  same revision is a no-op at the file-content level.
- The new secret orchestrator must separate "persisted successfully" from "runtime synced
  successfully" so the system can recover from sync failure without lying about state.
- If runtime sync fails during `ask_user_env`, the run must remain unresumed and the user
  must get an actionable failure, not a fake continue signal.
- If runtime sync fails for a settings-panel edit, the system should persist the secret
  state, mark runtime state stale, and reconcile later rather than provisioning new
  infrastructure just to complete a generic edit.
- The worktree is already dirty in unrelated runtime files. Keep each implementation
  slice reviewable and avoid touching those files until the plan reaches the provider
  contract phase.

## Plan Revision Notes

- 2026-04-22 / Codex: Initial draft created after adversarially revalidating the audit findings and narrowing the unproven Codex chat assumption to an explicit validation gate.
- 2026-04-22 / Codex: Revised the plan after residual-risk investigation. The effort is now explicitly organized around one backend-owned secret orchestration boundary, revision-based runtime reconciliation, and a clean split between settings persistence and paused-run execution.
