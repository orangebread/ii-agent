# Add Dual-Provider OAuth Storage And Deterministic Runtime Selection

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

After this change, a single user can connect both OpenAI and Anthropic OAuth accounts,
keep both stored safely, and use either runtime intentionally without one connection
silently disabling the other.

Observable outcomes after implementation:

- A user can connect OpenAI/Codex and Anthropic/Claude Code without losing the first connection.
- OAuth credentials are encrypted at rest for both providers.
- Sandbox bootstrap no longer depends on “whatever MCP setting was last marked active.”
- The system supports explicit runtime selection at the user default level and optional
  per-session override.
- Existing clients continue to function during migration through compatibility endpoints.

## Progress

- [x] (2026-04-16 14:05Z) Reviewed current `settings/mcp` design, sandbox bootstrap, and model-selection patterns.
- [x] (2026-04-16 14:15Z) Performed adversarial review of an initial “new tables for everything” strategy.
- [x] (2026-04-16 14:30Z) Revised the design to preserve `mcp_settings` as runtime config while moving OAuth secrets into first-class encrypted storage.
- [x] (2026-04-16 14:40Z) Drafted this ExecPlan in the repository.
- [ ] Implement schema changes and compatibility layer.
- [ ] Migrate current OpenAI/Codex and Anthropic/Claude Code OAuth flows.
- [ ] Add explicit selection semantics and update sandbox bootstrap.
- [ ] Add tests covering dual storage, switching, and migration safety.

## Surprises & Discoveries

- Observation: `create_mcp_settings()` deactivates all active MCP settings for the user before creating a new one.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py:59`

- Observation: sandbox bootstrap only loads active MCP settings, so current runtime behavior is coupled to global `is_active`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py:718`

- Observation: OpenAI/Codex auth is encrypted before storage, but Claude Code auth is currently stored directly in metadata JSON.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py:397`

- Observation: the repo already has a production-grade pattern for explicit provider/model selection via `sessions.model_setting_id`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py:290` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/models.py:40`

- Observation: `docs/exec-plans/` did not exist even though `docs/PLANS.md` requires active plans to live there.
  Evidence: repository listing before plan creation showed no `docs/exec-plans` directory.

## Decision Log

- Decision: Do not replace `mcp_settings` with a brand-new generalized runtime table in phase 1.
  Rationale: That would create unnecessary churn, migration risk, and API breakage. `mcp_settings` already holds non-secret runtime registration data and can remain the runtime-facing layer.
  Date/Author: 2026-04-16 / Codex

- Decision: Introduce a new encrypted OAuth credential store separate from `mcp_settings`.
  Rationale: Secrets, runtime registration, and selection state are different concerns. Current coupling is the core design flaw.
  Date/Author: 2026-04-16 / Codex

- Decision: Treat `is_active` as “enabled for registration,” not as “currently selected provider.”
  Rationale: Selection and enablement are separate states. Conflating them created last-write-wins behavior.
  Date/Author: 2026-04-16 / Codex

- Decision: Add explicit runtime selection with user default plus optional session override.
  Rationale: The repo already uses explicit session selection for model settings; that pattern is stable and understandable.
  Date/Author: 2026-04-16 / Codex

- Decision: Keep compatibility endpoints for `/mcp/codex` and `/mcp/claude-code` during migration.
  Rationale: Abrupt endpoint replacement would force frontend and integration churn before the backend behavior is stable.
  Date/Author: 2026-04-16 / Codex

## Outcomes & Retrospective

This plan defines the target architecture and implementation sequence but does not yet
implement it. The main correction from the initial strategy is scope discipline:
introduce first-class OAuth credential storage, but avoid inventing a broad new runtime
framework before the real defects are fixed.

Remaining gap: the repo still lacks the implementation, migrations, and compatibility tests.

## Context and Orientation

Current state:

- `mcp_settings` stores both MCP runtime config and tool-specific metadata in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/models.py`.
- The service for Codex and Claude Code OAuth lives in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py`.
- Sandbox bootstrap loads active MCP settings and writes auth files during startup in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py`.
- The model-selection subsystem provides a good pattern for explicit selection using
  `sessions.model_setting_id` in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/models.py`
  and resolution logic in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py`.

Terminology used in this plan:

- Provider connection: an encrypted, durable OAuth credential record for one user and one provider account.
- Runtime config: the non-secret MCP registration information needed to bootstrap a tool runtime such as Codex or Claude Code.
- Selection: the explicit choice of which enabled runtime should be the default for a user or overridden for a session.

Problem statement:

The current design stores runtime config and secrets together, deactivates all active MCP
settings on new create, and uses active settings as an implicit selection mechanism.
That fails the requirement to store both providers and switch intentionally.

## Proposed Final Design

### 1. New encrypted credential store

Add a new domain under `src/ii_agent/settings/provider_connections/` with:

- `models.py`
- `repository.py`
- `service.py`
- `schemas.py`
- `dependencies.py`
- `router.py`

Create a `provider_connections` table with fields similar to:

- `id`
- `user_id`
- `provider` (`openai`, `anthropic`)
- `product` (`codex`, `claude_code`)
- `external_account_id` nullable
- `display_name` nullable
- `encrypted_access_token`
- `encrypted_refresh_token`
- `encrypted_id_token` nullable
- `scopes` JSONB nullable
- `expires_at` nullable
- `last_refreshed_at` nullable
- `status` (`connected`, `expired`, `reauth_required`, `revoked`, `error`)
- `last_error` nullable
- `metadata` JSONB nullable
- timestamps

Use application-layer encryption via the existing encryption manager, matching the
`settings/llm` pattern instead of storing raw tokens in `mcp_metadata`.

### 2. Keep `mcp_settings`, but remove OAuth secrets from it

Retain `mcp_settings` as the runtime registration surface for:

- stdio/remote MCP server config
- tool type
- non-secret runtime options
- enabled/disabled state

Add a reference from `mcp_settings` metadata or schema-backed fields to a
`provider_connection_id`. Phase 1 can keep this in metadata for lower migration cost,
but the implementation should expose it as a typed field in service/router DTOs.

For Codex metadata, keep non-secret options such as:

- `model`
- `model_reasoning_effort`
- `search`
- `store_path`

For Claude Code metadata, keep only:

- `store_path`
- non-secret runtime flags if they are added later

### 3. Add explicit selection semantics

Selection must not depend on global `is_active`.

Phase 1 storage:

- Add `default_mcp_setting_id` nullable to `users` or user settings if there is an existing
  suitable profile/settings surface.
- Add `mcp_setting_id` nullable to `sessions` for per-session runtime override.

Preferred direction:

- `users.default_mcp_setting_id` = default enabled runtime for new sessions
- `sessions.mcp_setting_id` = optional explicit session override

Resolution rules:

1. If `sessions.mcp_setting_id` is set, use that.
2. Else if `users.default_mcp_setting_id` is set, use that.
3. Else fall back to deterministic compatibility behavior:
   first enabled `codex` setting if present, else first enabled `claude_code`, else none.

This mirrors the existing `model_setting_id` resolution pattern and removes reliance on
last-write-wins activation.

### 4. Update sandbox bootstrap

Revise sandbox bootstrap in
`/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/sandboxes/service.py`
to resolve the selected MCP runtime first, then materialize credentials and register the
corresponding runtime.

Required behavior:

- Load selected `mcp_setting`.
- Load its referenced `provider_connection`.
- Refresh the token if needed under a provider-specific lock.
- Write runtime auth files from decrypted credentials.
- Register the chosen runtime.

Secondary enabled MCP servers that are unrelated custom servers or Composio servers can
still be registered in parallel. The key change is that Codex/Claude Code selection
becomes deterministic rather than derived from all active rows.

### 5. Compatibility endpoints and migration

Preserve existing routes in
`/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/router.py`
for phase 1:

- `/mcp/codex`
- `/mcp/codex/openai/device/start`
- `/mcp/codex/openai/device/poll`
- `/mcp/claude-code`
- `/mcp/claude-code/oauth/start`
- `/mcp/claude-code/oauth/complete`

Internally, these routes should:

- create or update a `provider_connection`
- create or update the corresponding `mcp_setting`
- preserve any existing enabled setting for the other provider
- optionally set the new runtime as the user default if product rules say new connections
  should become the default

Migration steps:

1. Add schema and code for `provider_connections`.
2. Backfill OpenAI/Codex encrypted auth from `mcp_metadata.encrypted_auth_json`.
3. Backfill Claude Code auth from existing `mcp_metadata.auth_json` and immediately rewrite
   it into encrypted provider connection storage.
4. Strip raw secrets from `mcp_metadata`.
5. Set default selections for users with exactly one enabled runtime.

## Plan of Work

### Phase A: Schema and domain scaffolding

- Add the `provider_connections` domain under `src/ii_agent/settings/provider_connections/`.
- Add database migration for the new table and any new FK or selection columns.
- Wire the service into `src/ii_agent/core/container.py`.

### Phase B: OAuth flow refactor

- Refactor Codex OpenAI device OAuth in
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py`
  so successful login writes tokens into `provider_connections` instead of `mcp_metadata`.
- Refactor Claude Code OAuth completion to do the same.
- Remove direct storage of `auth_json` in Claude metadata responses except where explicitly
  requested for trusted internal consumers.

### Phase C: Selection semantics

- Add user default runtime selection and session override fields.
- Add a resolver service that chooses the effective MCP runtime for a session, following
  the precedence rules above.
- Stop using global active-settings iteration as the implicit selector for Codex/Claude Code.

### Phase D: Sandbox integration

- Update sandbox bootstrap to resolve the effective runtime.
- Materialize decrypted auth payloads into the correct files:
  `~/.codex/auth.json` and `~/.claude/.credentials.json`.
- Register the selected runtime plus any enabled non-provider MCP servers.

### Phase E: Cleanup and compatibility hardening

- Keep old API routes but move them to the new services internally.
- Add serialization guards so secret-bearing metadata is excluded unless explicitly requested.
- Add logging and metrics for token refresh, invalid credential state, and fallback path usage.

## Validation and Acceptance

Behavioral acceptance criteria:

- A user can connect OpenAI/Codex, then connect Anthropic/Claude Code, and both remain available.
- Connecting one provider does not disable the other provider’s runtime config.
- Claude Code OAuth credentials are no longer stored raw in `mcp_settings.metadata`.
- New sessions use the user default runtime when no session override is present.
- A session override can choose the non-default runtime and sandbox bootstrap honors it.
- Existing custom MCP servers and Composio servers still register correctly.

Tests to add or update:

- `src/tests/unit/settings/test_provider_connections_service.py`
- `src/tests/unit/settings/test_mcp_service_deep.py`
- `src/tests/api/settings/test_mcp_router.py`
- `src/tests/unit/engine/test_sandbox_service.py`
- any migration test location already used for DB migration/backfill coverage

Verification commands:

```bash
uv run pytest src/tests/unit/settings/test_provider_connections_service.py
uv run pytest src/tests/unit/settings/test_mcp_service_deep.py
uv run pytest src/tests/api/settings/test_mcp_router.py
uv run pytest src/tests/unit/engine/test_sandbox_service.py
uv run pytest -k "mcp or provider_connection or sandbox"
```

If Python files changed, run Ruff only on changed files:

```bash
uv run ruff check --fix-only <changed_python_files>
uv run ruff format <changed_python_files>
uv run ruff check <changed_python_files>
uv run ruff format --check <changed_python_files>
```

## Idempotence and Recovery

- The migration must be rerunnable without duplicating provider connections. Use
  deterministic lookup by `(user_id, provider, product, external_account_id)` where possible.
- Backfill should be safe to resume: if a provider connection already exists, update missing
  encrypted fields instead of creating a duplicate.
- Do not delete legacy secret fields until the new provider connection exists and the
  rewrite has committed successfully.
- If sandbox bootstrap fails due to invalid credentials, mark the connection
  `reauth_required` and preserve the runtime config so the user can reconnect without
  rebuilding all settings.

## Critical Review Of This Plan

Weakness 1: Adding both a new credential domain and selection columns increases scope.

Why this is still correct:
The alternative is to keep implicit selection through `is_active`, which is the root bug.
Selection has to become explicit somewhere.

Weakness 2: Reusing `mcp_settings` may look inelegant compared to a clean-slate runtime table.

Why this is still correct:
The repo already depends on `mcp_settings` in routers, services, tests, and sandbox bootstrap.
A clean-slate replacement is attractive architecture cosplay unless there is a hard need.

Weakness 3: User default plus session override may be more than the immediate request asks for.

Why this is still correct:
Only storing both credentials is insufficient. Without explicit resolution rules, the system
will regress back to hidden last-write-wins behavior.

## Plan Revision Note

This plan revises an earlier strategy that proposed introducing both a credential store and
a brand-new runtime profile framework. The revised version keeps `mcp_settings` as the
runtime configuration layer and limits new schema to what is actually needed: encrypted
provider connections plus explicit selection state.
