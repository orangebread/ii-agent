# OAuth Entry Test Coverage Map

This document maps the Gherkin behavior contract in
[`2026-04-16-oauth-entry-user-journeys.feature`](./2026-04-16-oauth-entry-user-journeys.feature)
to the automated coverage the repo should maintain.

## Why this exists

The auth experience regressed because the backend truth and frontend gating logic
drifted apart:

- backend allowed local dev bypass
- frontend cached a stale `iiOAuthAvailable=false`
- the staged OpenAI card still disabled `Continue with II`

That failure mode is not hypothetical anymore. Treat these tests as production
guardrails, not optional QA nice-to-haves.

## Coverage Layers

### 1. Backend API contract tests

These should live near:

- [`src/tests/api/auth/`](../../../src/tests/api/auth)
- [`src/tests/unit/auth/`](../../../src/tests/unit/auth)

Scenarios to cover:

- `GET /auth/providers`
  - local env + missing `II_CLIENT_ID` returns `ii_oauth_available=true`
  - local env + missing `II_CLIENT_ID` returns `dev_auth_bypass_enabled=true`
  - non-local env + missing `II_CLIENT_ID` returns `ii_oauth_available=false`
  - configured II returns `ii_oauth_available=true`
- `GET /auth/oauth/ii/login`
  - local bypass path returns a successful auth callback payload
  - real II path redirects to the IdP with PKCE + state
  - staged OpenAI is attached during local bypass path
  - staged OpenAI is attached during real II callback path
  - invalid pending connection is ignored or cleared safely
- `GET /auth/oauth/ii/callback`
  - invalid state is rejected
  - valid callback creates app token payload
  - valid callback clears consumed pending OpenAI state
- `POST /auth/oauth/openai/device/poll`
  - successful staging returns `pending_connect_id`
  - staging never mints app session directly

### 2. Frontend route/component tests

These should live near:

- [`frontend/src/app/routes/login.tsx`](/Volumes/OWC%20Envoy%20Ultra/projects/_tools_/ii-agent/frontend/src/app/routes/login.tsx)

Scenarios to cover:

- login page with providers `{ ii_oauth_available: true, dev_auth_bypass_enabled: true }`
  - `Continue with II` is enabled
  - bypass explanatory copy is visible
- login page with providers `{ ii_oauth_available: false, dev_auth_bypass_enabled: false }`
  - `Continue with II` is disabled
  - configuration warning is visible
- transient `/auth/providers` failure
  - login page does not permanently disable II
  - retry or subsequent successful load updates UI
- staged OpenAI state
  - successful staged card renders
  - staged card reuses refreshed provider availability
  - staged card does not show the “cannot finish” warning when bypass is active

### 3. Browser E2E tests

These should be added with whatever browser runner the team prefers, but the
coverage should be explicit:

- local env, no `II_CLIENT_ID`
  - open `/login`
  - click `Continue with II`
  - verify app session exists and app loads
- local env, no `II_CLIENT_ID`, staged OpenAI
  - stage OpenAI through a mocked or intercepted device flow
  - click `Continue with II`
  - verify app session exists
  - verify Codex setting is attached
- configured II env
  - click `Continue with II`
  - verify redirect to II auth URL
  - mock callback and verify app session
- UI resilience
  - simulate initial provider lookup failure
  - recover provider lookup
  - verify button state updates correctly

## Recommended Test Naming

Use scenario-shaped names instead of implementation names:

- `test_auth_providers_local_env_enables_dev_bypass`
- `test_ii_login_local_bypass_creates_app_session`
- `test_ii_login_local_bypass_attaches_staged_openai_codex`
- `test_login_page_keeps_ii_continue_enabled_when_dev_bypass_active`
- `test_login_page_recovers_from_transient_auth_provider_failure`
- `test_staged_openai_card_uses_refreshed_provider_availability`

## Minimum Release Gate

Before merging auth/login changes, the following should be required:

- backend auth API contract tests
- frontend login route tests
- at least one browser E2E for local bypass
- at least one browser E2E for staged OpenAI + continue path

If any of those are missing, you are relying on manual discovery again.
