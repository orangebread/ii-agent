# Close OAuth-To-Model Readiness Gaps

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

After this change, a user who completes OpenAI/Codex OAuth and/or Anthropic Claude OAuth
can open Agent Settings, see provider-specific executable models in the Model tab, select
one, and use the system without hitting a hidden downstream blocker. Codex and Claude Code
must behave as distinct provider/runtime lanes, not as vague connection badges.

Observable outcomes after implementation:

- Codex OAuth creates a real OpenAI/Codex-backed model-selection path in `/v1/user-settings/models`.
- Anthropic OAuth creates a real Claude Code-backed model-selection path in `/v1/user-settings/models`.
- The home route no longer hard-gates authenticated users on Codex/OpenAI auth.
- The Model tab explains empty or blocked states instead of rendering a blank list, and it filters inventory by the selected provider lane when the user chooses Codex or Claude Code.
- Existing sessions can switch to a newly selected model; selection is not trapped by a
  stale `sessions.model_setting_id` or a stale `sessions.mcp_setting_id`.
- Anthropic OAuth-backed models resolve to a live `auth_token` for both chat and agent execution while the stored access token is still valid.
- Codex OAuth-backed models resolve to ChatGPT/Codex bearer execution against `https://chatgpt.com/backend-api/codex` with the required `ChatGPT-Account-ID` header.

## Progress

- [x] (2026-04-21 13:10Z) Audited current OAuth, model selection, session resolution, and frontend gating paths.
- [x] (2026-04-21 13:30Z) Validated the external product constraint: OpenAI API access still uses API keys, while ChatGPT/Codex OAuth is a separate grant.
- [x] (2026-04-21 13:45Z) Drafted this ExecPlan in the repository.
- [x] (2026-04-21 23:55Z) Added backend support for provider-backed Anthropic OAuth model rows, config resolution, and truthful availability states.
- [x] (2026-04-22 00:05Z) Fixed session model resolution so explicit model selection overrides stale session state.
- [x] (2026-04-22 00:15Z) Updated the frontend home/model UX to remove the Codex gate and render truthful model inventory states.
- [x] (2026-04-22 00:30Z) Added targeted regression tests and ran backend/frontend validation commands that are actually available in this environment.
- [x] (2026-04-22 04:10Z) Added Codex-managed model materialization and direct Codex execution config resolution.
- [x] (2026-04-22 04:25Z) Aligned session runtime selection with the selected provider-backed model and active agent type.
- [x] (2026-04-22 04:40Z) Updated the frontend to filter model inventory by Codex vs Claude Code and auto-select a compatible model when the provider lane changes.

## Surprises & Discoveries

- Observation: the prior dual-provider runtime work already landed `provider_connections`, `mcp_settings.provider_connection_id`, `users.default_mcp_setting_id`, and `sessions.mcp_setting_id`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/migrations/versions/20260416_000003_provider_connections_and_runtime_selection.py`

- Observation: the authenticated home route still blocks on Codex/OpenAI auth even after runtime selection was made explicit.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/app/routes/home.tsx:436`

- Observation: `model_settings` still has no typed link to `provider_connections`, so OAuth-backed model execution cannot be resolved cleanly.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/models.py:36`

- Observation: the current session-resolution flow ignores a newly selected model once `sessions.model_setting_id` is populated, so model switching can silently fail.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py:306`

- Observation: OpenAI API docs still describe API-key authentication for OpenAI API access, and the Codex/ChatGPT OAuth grant is documented as a separate CLI-oriented authorization that can create API keys but is not itself the secret API key used by this repo today.
  Evidence: [OpenAI production best practices](https://platform.openai.com/docs/guides/production-best-practices/model-overview) and [Codex CLI and Sign in with ChatGPT](https://help.openai.com/en/articles/11381614)

- Observation: Anthropic model execution code already supports `auth_token`, but the resolved model config path does not supply one.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/models/anthropic/claude.py:476` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/anthropic/provider.py:123`

- Observation: `model_settings` is unique on `(model_id, provider, user_id)`, so provider-managed rows collide with API-key rows unless the internal row key is separated from the provider-visible model ID.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/models.py:68`

- Observation: the realtime query handler instantiates the agent from `session_info.agent_type`, not directly from the latest submitted payload, so session backfill has to update `agent_type` whenever the user switches lanes.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py:96`

## Decision Log

- Decision: Codex OAuth-backed execution is allowed, but only through the Codex ChatGPT backend contract, not by pretending the grant is a normal OpenAI API key.
  Rationale: the stored Codex OAuth payload contains a bearer access token and ChatGPT account metadata, which can back the Codex responses endpoint, but it is still not the same thing as a reusable OpenAI API key.
  Date/Author: 2026-04-22 / Codex

- Decision: add a typed `provider_connection_id` to `model_settings` instead of hiding OAuth provenance in the generic `params` JSON.
  Rationale: provider-backed credentials are not a model-tuning parameter. Smuggling auth provenance into `params` would be schema theater and would make validation and migration worse.
  Date/Author: 2026-04-21 / Codex

- Decision: lazily sync Anthropic provider-backed model rows inside the model-setting service.
  Rationale: this heals existing users with stored Anthropic OAuth connections without needing a brittle one-off backfill and avoids adding more orchestration to the MCP service.
  Date/Author: 2026-04-21 / Codex

- Decision: treat expired Anthropic OAuth access tokens as unavailable for model execution until explicit refresh support exists in the model path.
  Rationale: Claude Code runtime may be able to refresh itself, but the chat and agent model clients in this repo cannot. Marking expired access tokens as executable would be another fake-ready state.
  Date/Author: 2026-04-21 / Codex

- Decision: change session resolution so an explicitly requested model selection wins over stale `sessions.model_setting_id`.
  Rationale: the frontend already sends the selected model on each run. Ignoring that once a session has history makes the picker untrustworthy.
  Date/Author: 2026-04-21 / Codex

- Decision: give provider-managed rows stable internal keys and keep the provider-visible model ID in `params.provider_model_id`.
  Rationale: without that separation, Codex/Claude-managed rows collide with user API-key rows for the same provider/model and the whole “both paths can coexist” story falls apart.
  Date/Author: 2026-04-22 / Codex

## Outcomes & Retrospective

Implemented:

- `model_settings` now supports a typed `provider_connection_id`, with a migration at `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/migrations/versions/20260421_000004_provider_backed_model_settings.py`.
- Anthropic Claude OAuth and OpenAI/Codex OAuth now both lazily materialize managed model rows through `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py`.
- Managed Anthropic rows resolve to live `auth_token` credentials, and managed Codex rows resolve to bearer-authenticated Codex responses config with the required account header.
- Provider-managed rows now use internal row keys, so they can coexist with user API-key rows for the same provider/model.
- Explicit model selection now wins over stale session state, and runtime selection is synchronized to the selected provider-backed model or agent lane before the run starts.
- The home route no longer blocks Anthropic-only users behind an OpenAI/Codex gate.
- The Model tab now keeps full inventory locally, while the rest of the app only sees selectable models and the UI filters that inventory by Codex vs Claude Code when the user picks a lane.

Validation executed:

- `./.venv/bin/python -m pytest -q src/tests/unit/settings/test_llm_provider_managed_models.py src/tests/unit/settings/test_mcp_runtime_selection.py src/tests/unit/sessions/test_session_runtime_selection.py`
  Result: `11 passed`
- `./.venv/bin/python -m compileall ...changed Python files...`
  Result: success
- `frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json`
  Result: success
- `frontend/node_modules/.bin/vite build --outDir /tmp/ii-agent-frontend-build`
  Result: blocked by an existing local Rollup native-module/code-signature issue in `frontend/node_modules`, not by a TypeScript error in this change.

Residual risk:

- `npm run lint` is currently not a usable validator in this checkout because ESLint 9 cannot find an `eslint.config.(js|mjs|cjs)` file. That is a repo/tooling issue, not a failure introduced by this change.
- `vite build` is currently blocked in this checkout by Rollup’s native optional dependency failing to load on this machine due a local code-signature mismatch inside `frontend/node_modules/.pnpm/@rollup+rollup-darwin-arm64...`. That is an environment/runtime issue, not a TypeScript contract failure from this change.
- The pre-existing Anthropic provider unit test file at `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/chat/test_chat_llm_anthropic_provider.py` is currently red against the repo’s current `Message` schema because it still uses a non-UUID `session_id` fixture. I did not fold that unrelated fixture repair into this change.

## Context and Orientation

Relevant backend files:

- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/models.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/repository.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/schemas.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/provider_connections/service.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/anthropic/provider.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/models/utils.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/service.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/core/container.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/migrations/versions/20260416_000003_provider_connections_and_runtime_selection.py`

Relevant frontend files:

- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/app/routes/home.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/contexts/auth-context.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent-setting/index.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent-setting/model-setting.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/services/settings.service.ts`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/typings/settings.ts`

Definitions used here:

- Provider-backed model: a `model_settings` row that does not store an encrypted API key and instead resolves credentials from a `provider_connections` row.
- Selectable model: a model entry that the user can actually choose for execution right now.
- Truthful empty state: a UI state that explains why no selectable model exists and what valid next step is available.

## Gherkin Behavior Contract

```gherkin
Feature: OAuth-backed model readiness

  Background:
    Given the user is authenticated
    And the backend is the source of truth for whether a model is selectable

  Scenario: Anthropic OAuth unlocks model selection
    Given the user completed Anthropic Claude OAuth successfully
    When they open Agent Settings and view the Model tab
    Then Anthropic models are listed as selectable
    And selecting one updates the active run model
    And the next run succeeds without asking for a manual API key

  Scenario: Anthropic-only users are not blocked by a Codex gate
    Given the user completed Anthropic Claude OAuth successfully
    And they have not connected OpenAI/Codex
    When they land on the home route
    Then the authenticated app loads
    And the user is not forced into an OpenAI-only onboarding gate

  Scenario: Codex OAuth unlocks Codex-backed model selection
    Given the user completed OpenAI/Codex OAuth successfully
    When they select the Codex lane and open Agent Settings -> Model
    Then Codex-backed models are listed as selectable
    And selecting one updates the active run model
    And the next run resolves the Codex runtime and model config together

  Scenario: Model selection updates existing sessions
    Given the user already has a session with a previously chosen model
    When they choose a different selectable model and submit a new run
    Then the backend resolves the newly requested model
    And the session uses that model for the run

  Scenario: Expired Anthropic OAuth does not create a fake-ready model
    Given a provider-backed Anthropic model exists
    And the stored access token is no longer valid for direct model execution
    When the user opens the Model tab
    Then that model is shown as unavailable
    And the UI explains that reauthentication is required
```

## Plan of Work

### Phase A: Backend model truth

1. Add `provider_connection_id` to `model_settings` in:
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/models.py`
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/migrations/versions/<new revision>.py`

2. Extend model DTOs in `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/schemas.py` so the API can describe:
   - credential source
   - managed/provider-backed state
   - selectability
   - availability reason
   - runtime product (`codex` vs `claude_code`)
   - provider-backed execution headers/token fields on resolved `ModelConfig`

3. Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py` to:
   - fix the existing `configs` vs `params` create bug
   - fix system model lookup by `model_id`
   - inject `ProviderConnectionService`
   - lazily sync Anthropic OAuth-backed and Codex OAuth-backed model rows from `provider_connections`
   - resolve provider-backed Anthropic configs to `auth_token`
   - resolve provider-backed Codex configs to bearer-authenticated Codex responses config
   - mark managed rows unavailable when no live access token exists

4. Update the model clients:
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/llm/anthropic/provider.py`
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/models/utils.py`
   so both chat and agent runtime accept `auth_token`.

### Phase B: Session and chat correctness

1. Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py`
   and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/service.py`
   so an explicitly requested model selection overrides stale `sessions.model_setting_id`.

2. Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/chat/application/chat_service.py`
   so unavailable provider-backed models are rejected before runtime execution.

### Phase C: Frontend truth and flow

1. Remove the Codex-only home gate from `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/app/routes/home.tsx`.

2. Update the model inventory flow in:
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/contexts/auth-context.tsx`
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent-setting/index.tsx`
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/agent-setting/model-setting.tsx`
   - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/typings/settings.ts`

   Required behavior:
   - global app state keeps only selectable models for runtime use
   - the Model tab can still render unavailable managed models with reasons
   - the Model tab refreshes when opened
   - Codex and Claude Code lanes show provider-specific model inventories
   - provider lane switches auto-select a compatible model instead of leaving stale cross-provider state

3. Tighten downstream copy where a missing model still blocks submission so the user is told exactly where to recover.

## Validation and Acceptance

Backend validation commands:

```bash
cd /Volumes/OWC\ Envoy\ Ultra/projects/_tools_/ii-agent
uv run pytest src/tests/unit/settings/test_provider_connection_service.py
uv run pytest src/tests/unit/settings/test_llm_service_deep.py
uv run pytest src/tests/unit/chat/test_chat_llm_anthropic_provider.py
uv run pytest src/tests/unit/settings/test_mcp_runtime_selection.py
```

Frontend validation commands:

```bash
cd /Volumes/OWC\ Envoy\ Ultra/projects/_tools_/ii-agent/frontend
npm run build
npm run lint
```

Acceptance checks:

- Anthropic OAuth completion followed by `GET /v1/user-settings/models` returns selectable Anthropic rows.
- Selecting a different model for an existing session changes the resolved model on the next run.
- Authenticated users with Anthropic OAuth but no Codex connection reach the home route normally.
- OpenAI OAuth-only users see truthful guidance in the Model tab instead of a blank list or false-ready model options.

## Idempotence and Recovery

- The Anthropic managed-model sync must be idempotent: repeated calls should update or no-op, not duplicate rows.
- Manual API-key-backed model rows must not be overwritten by background sync.
- If the new migration fails locally, rerunning `uv run alembic upgrade head` after fixing the revision should be safe because the new column/index additions are bounded to `model_settings`.
- If frontend changes regress runtime selection, the backend still remains the source of truth for selectability; the UI can be corrected without changing stored credentials again.
