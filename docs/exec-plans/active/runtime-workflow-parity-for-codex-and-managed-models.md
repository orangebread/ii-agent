# Runtime Workflow Parity For Codex-Backed Agent Sessions

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

After this effort, Codex-backed agent sessions should participate in the same
platform workflow semantics as standard agent sessions: plan generation,
milestone-based build execution, result delivery, pause/resume, and approval or
input handling. The platform must stop encoding workflow behavior as
"whatever the current runtime happens to support by accident."

This effort also restores a continuity invariant that existed on `main` before
the recent provider/runtime refactors: agent-session continuity is anchored to
the session or fork execution context, not to the latest model or provider the
user happens to pick in global UI state.

Observable outcomes after implementation:

- First-turn website build prompts enter the same platform Plan -> Build -> Result
  journey for Codex-backed and non-Codex-backed sessions.
- Switching the currently selected provider or model does not silently rewrite the
  execution identity of an existing agent session or project.
- Plan generation no longer depends on one runtime-specific mechanism such as direct
  injected tools. The platform owns a canonical plan contract and persists the same
  milestone data regardless of runtime.
- `continue_run` works for Codex-backed sessions using the same pause UI and command
  surface already used by non-Codex runs.
- Frontend workflow options are driven by explicit backend capabilities, not scattered
  `runtime_product == "codex"` checks.
- Realtime handlers no longer reject Codex plan/resume paths up front.

## Progress

- [x] (2026-04-23 16:10Z) Revalidated the current parity failures in the repo before drafting the strategy.
- [x] (2026-04-23 16:10Z) Confirmed there is no Taskplane state in this repo; this ExecPlan is the active orchestration document for the parity work.
- [x] (2026-04-23 16:10Z) Mapped the current failure seams across frontend routing, realtime handlers, agent factory branching, and Codex transport behavior.
- [x] (2026-04-23 16:25Z) Reviewed official Codex App Server documentation to verify whether dynamic tools, approvals, and user-input flows are actually available.
- [x] (2026-04-23 16:35Z) Drafted the target architecture, phased implementation plan, risks, and validation gates.
- [x] (2026-04-23 20:30Z) Compared current behavior against `main` and identified the original continuity contract: agent sessions were pinned at the session or fork boundary and `continue_run` depended on that invariant.
- [x] (2026-04-23 20:45Z) Revised the plan to restore session continuity, choose a run-level execution binding, narrow scope to Codex-backed agent sessions, and add reload or modify-plan acceptance.
- [x] (2026-04-23 22:15Z) Performed a second adversarial review and tightened the implementation contract around typed resume checkpoints, mixed-version rollout, and frontend bootstrap ordering.
- [x] (2026-04-23 23:35Z) Landed the first backend parity slice: agent sessions now keep backfill-only defaults, `RunTask.data` stores typed execution bindings and standard pause checkpoints, `continue_run` resolves runtime identity from the stored binding first, and session bootstrap exposes additive runtime capability fields.
- [x] (2026-04-24 01:15Z) Landed the second backend parity slice: Codex App Server now opts into `experimentalApi`, built-in approval requests persist typed Codex checkpoints and emit pause events, `continue_run` resumes Codex approval checkpoints instead of hard failing, and the standard pause writer no longer overwrites Codex-owned checkpoints.
- [x] (2026-04-24 01:40Z) Performed an adversarial code review of the landed backend slices, fixed pause-checkpoint ordering, defensive checkpoint parsing, and Codex approval-decision fallback gaps, and added focused protocol tests for unsupported dynamic-tool and user-input requests.
- [x] (2026-04-24 03:05Z) Verified the App Server protocol shape against current official docs and the OpenAI Codex source: dynamic tools use `thread/start.dynamicTools` plus `item/tool/call`, approvals respond with `{ decision }`, and `item/tool/requestUserInput` responds with an `answers` map.
- [x] (2026-04-24 03:30Z) Implemented Phase 1 capability exposure for the now-supported Codex workflow surface: platform plan, plan modification, dynamic tools, approvals, user input, pause/resume, and persistent threads.
- [x] (2026-04-24 04:15Z) Implemented the Phase 3 Codex runtime bridge: `agent.add_tool()` registers App Server dynamic tools, host tools execute on `item/tool/call`, approval responses use the typed App Server response envelope, and user-input requests persist typed checkpoints and resume through `continue_run`.
- [x] (2026-04-24 04:35Z) Implemented the Phase 4 frontend parity slice: plan mode is no longer hidden or rerouted based on Codex runtime product, and the HITL UI can send Codex-specific approval decisions plus generic user-input answers.
- [x] (2026-04-24 04:45Z) Revised Phase 2 based on protocol evidence: full workflow-service extraction is not required for this parity slice because the single host-owned plan tool now works across both standard and Codex runtime adapters. Keep deeper plan persistence extraction as a follow-up refactor, not a release blocker.
- [x] (2026-04-23 21:05Z) Closed the final implementation gaps found during code review: thread-level Codex protocol enums now use the actual JSON values, Codex `acontinue_run()` matches the standard agent iterator contract, command-only execpolicy amendments are guarded, permissions approvals use the permissions response shape, and standard `continue_run` keeps its legacy session-store fallback.
- [x] (2026-04-23 21:10Z) Verified OAuth persistence regression coverage for OpenAI Codex device OAuth, Claude Code OAuth provider-connection persistence, and provider-connection upsert behavior.
- [x] (2026-04-23 21:15Z) Executed the focused release validation set for runtime checkpoints, Codex runtime protocol bridging, session runtime capabilities, continue-run routing, Python lint/format, TypeScript compile, and targeted frontend lint.
- [x] (2026-04-24) Began environment-contract hardening: pinned the sandbox OpenAI Codex CLI package to `@openai/codex@0.124.0`, added production/runtime capability gates, added a `start.sh` local Docker App Server probe that disables Codex workflow capabilities for that startup when the contract is not verified, and added an opt-in `codex_smoke` protocol smoke test for local Docker images.

## Surprises & Discoveries

- Observation: Codex parity is blocked less by model capability than by repo choices. The current transport explicitly cancels approvals, cancels user-input requests, and returns failure for `item/tool/call`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py:207-254`

- Observation: Codex runtime sessions are structurally excluded from plan and resume before the runtime is even asked to participate.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/plan.py:71-76` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py:155-161`

- Observation: the agent factory treats Codex as a separate runtime system, not as an alternate implementation of the same runtime contract. Connector injection and task-agent delegation are dropped at construction time.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py:129-149`

- Observation: the current plan flow is implemented as an injected tool side channel. `MilestoneTool` writes plan data directly into session metadata and publishes `plan.milestone.generated` itself.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/plan/milestone.py:14-189`

- Observation: the realtime event converter already has a runtime-neutral abstraction for pause, tool confirmation, tool results, reasoning deltas, and completion. The weak seam is below the converter, not above it.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/events/converter.py:249-330`

- Observation: frontend plan behavior is currently derived from local UI mode plus hard-coded Codex exclusions, which is the wrong boundary. The UI is compensating for backend/runtime drift instead of consuming a capability contract.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/hooks/use-question-handlers.tsx:333-380` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/question-input.tsx:206-226`

- Observation: official Codex App Server docs explicitly support experimental dynamic tools, approval requests, and tool-driven user input when the client opts into `experimentalApi`.
  Evidence: [OpenAI App Server docs](https://developers.openai.com/codex/app-server) sections covering `initialize.capabilities.experimentalApi`, dynamic tool calls, `tool/requestUserInput`, and approval flows.

- Observation: Claude Code is not the same category of parity problem. In this repo it remains an orchestrated tool path inside the standard agent rather than a full runtime replacement.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py:129-149` only branches for `runtime_product == "codex"`

- Observation: `main` pinned agent-session model identity at the session boundary. `validate_and_prepare_for_run()` only backfilled `session.model_setting_id` when missing, and `continue_run` resumed from that pinned setting plus paused run state.
  Evidence: validated against `main:src/ii_agent/sessions/service.py:453-468` and `main:src/ii_agent/realtime/handlers/continue_run.py:120-160`

- Observation: the current refactor changed that contract. `validate_and_prepare_for_run()` now rewrites `session.model_setting_id` and `session.mcp_setting_id` whenever the resolved model or runtime differs, which means a later UI selection can mutate the resume context of an existing session.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/service.py:503-521`

- Observation: provider-managed model rows are currently treated as both discoverability catalog and execution identity. The sync path deletes managed rows when the provider connection is missing or unsupported, which is the wrong ownership model for long-lived session continuity.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/llm/service.py:454-464`

- Observation: product docs on `main` explicitly say chat mode supports "Switch models mid-thread". They do not say the same for agent mode. Agent mode is described around session or project iteration and session forking.
  Evidence: validated against `main:docs/PRODUCT_SENSE.md:58-65`

- Observation: the current OAuth integration is already isolated from agent workflow handlers. OpenAI device-code login and Claude Code OAuth both terminate in `ProviderConnectionService.upsert_connection(...)`, and model execution later derives live credentials from that stored provider-connection state.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py:439-477`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py:675-715`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/provider_connections/service.py:106-172` plus `:301-349`

- Observation: the initial checkpoint slice still had a race. Standard-runtime pause checkpoints were written after the pause event was already emitted, which meant the UI could show a resumable pause before host-side resume state was durable.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/base.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/realtime/test_base_handler_process_stream.py`

- Observation: Codex approval decisions are constrained by the runtime request payload. Assuming `approve_session` is always legal is false; some approval requests only advertise single-use `accept`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/engine/test_codex_runtime_agent.py`

- Observation: mixed-version rollout needs defensive checkpoint parsing, not optimistic parsing. Invalid `execution_binding` or `resume_checkpoint` blobs should degrade to compatibility fallback instead of exploding `continue_run`.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/tasks/checkpoint_service.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/tasks/test_run_checkpoint_service.py`

- Observation: the current App Server protocol wraps approval responses in a result object with a `decision` field. Returning a raw string is not the current primary-source protocol shape.
  Evidence: OpenAI Codex source `/tmp/openai-codex/codex-rs/app-server-protocol/src/protocol/v2.rs` and `/tmp/openai-codex/codex-rs/app-server-protocol/src/protocol/common.rs`, cross-checked against [OpenAI App Server docs](https://developers.openai.com/codex/app-server).

- Observation: App Server dynamic tools are registered on `thread/start`, not `thread/resume`. A Codex thread created without workflow tools should not be reused for plan runs that need host dynamic tools.
  Evidence: OpenAI Codex source `ThreadStartParams.dynamic_tools` exists while `ThreadResumeParams` has no equivalent dynamic-tools field.

- Observation: `item/tool/requestUserInput` and `mcpServer/elicitation/request` are two different user-input protocols. Collapsing both into the MCP `{ action, content }` response shape would be wrong for tool user-input questions.
  Evidence: OpenAI Codex source `ToolRequestUserInputResponse { answers }` and `McpServerElicitationRequestResponse { action, content }`.

- Observation: thread-level App Server parameters do not use the same casing as turn-scoped sandbox policy objects. `approvalPolicy` expects values like `untrusted`, and thread `sandbox` expects `workspace-write`; `sandboxPolicy.type` remains `workspaceWrite`.
  Evidence: OpenAI Codex source `AskForApproval`, `SandboxMode`, and `SandboxPolicy` serde declarations in `/tmp/openai-codex/codex-rs/app-server-protocol/src/protocol/v2.rs`, plus focused assertions in `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/engine/test_codex_runtime_agent.py`.

- Observation: `acontinue_run()` is a synchronous factory for an async iterator in the standard agent contract. Making the Codex implementation itself `async` returns a coroutine to `ContinueRunHandler`, which breaks resume execution at runtime even if direct unit tests `await` it.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/agent.py:1379-1506`, `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py`, and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`.

- Observation: standard-runtime `continue_run` must keep the pre-existing AgentSessionStore fallback when no durable task row is available. Codex should require a typed App Server checkpoint, but standard paused runs should not fail earlier than they did before this parity work.
  Evidence: `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py` and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/realtime/test_socket_handlers_r4.py::TestContinueRunHandlerHandle`.

- Observation: not every App Server method ending in `requestApproval` uses the `{ decision }` response envelope. `item/permissions/requestApproval` responds with a granted permissions profile and scope.
  Evidence: OpenAI Codex source `PermissionsRequestApprovalResponse` in `/tmp/openai-codex/codex-rs/app-server-protocol/src/protocol/v2.rs`, plus focused assertions in `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/engine/test_codex_runtime_agent.py`.

## Decision Log

- Decision: implementation scope is Codex-backed agent sessions first, while preserving continuity invariants for all agent sessions.
  Rationale: Codex is the runtime replacement that currently breaks plan and continue behavior. Claude Code is not the same runtime shape in this repo, so claiming "all managed sessions" would be false precision.
  Date/Author: 2026-04-23 / Codex

- Decision: the platform will introduce an explicit runtime capability contract before adding more Codex behavior.
  Rationale: otherwise every handler and component will continue to encode its own private view of what Codex can or cannot do.
  Date/Author: 2026-04-23 / Codex

- Decision: plan/build/result semantics will be moved upward into a platform workflow layer instead of remaining encoded as runtime-specific tool side effects.
  Rationale: full parity is impossible while plan persistence depends on `agent.add_tool(MilestoneTool)` and Codex does not support injected tools.
  Date/Author: 2026-04-23 / Codex

- Decision: Codex parity should use App Server capabilities that already exist, rather than a fake parallel workflow invented by II-Agent.
  Rationale: official docs show Codex App Server supports approvals, dynamic tools, and tool-driven user input behind `experimentalApi`. The repo is currently opting out by implementation, not blocked by the underlying protocol.
  Date/Author: 2026-04-23 / Codex

- Decision: the initial Codex bridge should focus on workflow-critical parity only.
  Rationale: full native-tool equivalence is broader than the user problem. The first target is plan submission, milestone execution continuity, approvals, and user input. Duplicating every tool immediately is a recipe for delay and review noise.
  Date/Author: 2026-04-23 / Codex

- Decision: frontend mode availability will be capability-driven from backend/session state, not inferred from `runtime_product`.
  Rationale: the frontend should render what the backend/runtime contract actually supports for this session, not what a static model label implies.
  Date/Author: 2026-04-23 / Codex

- Decision: agent sessions keep the original `main` continuity contract unless the product explicitly chooses otherwise.
  Rationale: on `main`, model identity was effectively pinned per session or fork. Silent in-place rebinding of agent sessions is a product change and has already made resume semantics unsafe.
  Date/Author: 2026-04-23 / Codex

- Decision: `continue_run` and any future resume flow must bind to per-run execution state, not to the session row's current mutable model or runtime fields.
  Rationale: once session identity can drift, using `session.model_setting_id` for resume is no longer defensible.
  Date/Author: 2026-04-23 / Codex

- Decision: provider-managed model rows must become durable identity records or be replaced by a durable binding layer; they cannot be deleted as part of catalog sync if sessions or projects depend on them.
  Rationale: discoverability sync and session continuity have different lifecycles. Collapsing them guarantees either broken reauth or broken session resume.
  Date/Author: 2026-04-23 / Codex

- Decision: runtime capabilities must have one authoritative frontend transport: `SessionInfo` bootstrap for reload correctness, plus an additive realtime update event only when an explicit session rebind occurs.
  Rationale: live-only capability events will recreate the same reload/replay desync that already exists elsewhere.
  Date/Author: 2026-04-23 / Codex

- Decision: preserve the existing OAuth handshake and provider-credential authority as-is.
  Rationale: the working OpenAI and Anthropic OAuth flows already have a clear seam: MCP auth endpoints persist provider credentials into `ProviderConnectionService`, and runtime/model resolution consumes those stored credentials later. Parity work should happen above that layer, not by rewriting working auth flows.
  Date/Author: 2026-04-23 / Codex

- Decision: model swapping semantics stay product-specific instead of being flattened into one global rule.
  Rationale: chat mode is intentionally request-scoped and supports mid-thread model switching, while agent mode depends on stable session or fork identity. Treating those as the same behavior is what created the current continuity drift.
  Date/Author: 2026-04-23 / Codex

- Decision: host-owned standard-runtime pause checkpoints must be durable before the pause event is emitted.
  Rationale: advertising resumability before the checkpoint commit lands recreates the exact resume race this slice is supposed to remove.
  Date/Author: 2026-04-23 / Codex

- Decision: Codex approval resume must honor `allowed_decisions` from the persisted request and degrade safely when session-wide approval is unavailable.
  Rationale: otherwise the new additive continue UI can emit decisions the App Server never offered, turning a valid paused run into a protocol error.
  Date/Author: 2026-04-23 / Codex

- Decision: the parity slice will bridge the existing host-owned plan tools into Codex App Server dynamic tools instead of blocking on a larger plan-workflow service extraction.
  Rationale: this achieves the user-visible parity target with a smaller, reviewable adapter change. A deeper plan persistence refactor is still useful, but it is no longer required to make Codex plan generation and modification work.
  Date/Author: 2026-04-24 / Codex

- Decision: Codex dynamic-tool thread reuse is gated by a registered-tool fingerprint.
  Rationale: current App Server dynamic tools are supplied on `thread/start`; reusing a thread started without the needed tools would make plan-mode tool calls impossible or non-deterministic.
  Date/Author: 2026-04-24 / Codex

- Decision: Codex user-input checkpoints preserve the original server request kind and respond with protocol-specific payloads.
  Rationale: App Server tool user-input uses an `answers` map, while MCP elicitations use `{ action, content }`. Treating both as one generic response shape would be a latent resume bug.
  Date/Author: 2026-04-24 / Codex

- Decision: Codex runtime parameter values are asserted against the App Server JSON protocol, not Rust enum variant names or inferred camelCase.
  Rationale: the protocol uses different casing at different layers; guessing from nearby fields produced invalid `approvalPolicy` and `sandbox` values.
  Date/Author: 2026-04-23 / Codex

- Decision: execpolicy-amendment approval responses are command-approval-only.
  Rationale: file-change approvals do not support `acceptWithExecpolicyAmendment`; applying that object-shaped decision there would turn a valid approval into a protocol error.
  Date/Author: 2026-04-23 / Codex

- Decision: Codex permissions approvals grant the requested permissions on approve and return an empty permissions profile on reject/cancel.
  Rationale: the App Server permissions approval protocol has no `{ decision: decline }` equivalent, so the safest denial is to grant no additional permissions while preserving protocol shape.
  Date/Author: 2026-04-23 / Codex

- Decision: `scripts/start.sh` is a local preflight and capability-degradation surface, not the authoritative Codex runtime contract.
  Rationale: installing or validating a host `codex` binary proves the wrong surface. The contract must live in the sandbox image/template used by `CodexRuntimeAgent`; local startup can probe a Docker image and disable workflow capabilities for that launched backend when the image is missing or incompatible.
  Date/Author: 2026-04-24 / Codex

- Decision: production Codex App Server workflow capabilities require an explicit smoke-verification flag.
  Rationale: the UI must not expose Plan or resume flows for Codex-backed sessions unless the configured sandbox image/template has been verified against the expected App Server protocol. Non-production Docker can be probed locally; E2B/production templates need release smoke evidence.
  Date/Author: 2026-04-24 / Codex

## Outcomes & Retrospective

Implementation is functionally complete for the scoped Codex workflow-parity slice. Focused release validation and OAuth persistence regression coverage are complete. Initial environment-contract hardening has started. The remaining work is full environment-level validation against the intended E2B/production sandbox Codex CLI image/template and any product decision about rollout timing.

What is already clarified:

- The current failure is architectural, not a single bug.
- Codex App Server can support the required interaction patterns if II-Agent bridges them correctly.
- The right abstraction is "workflow capabilities over runtime adapters," not "special-case Codex in each handler."
- The original `main` workflow depended on stable session execution identity for agent mode; the recent refactor silently changed that contract.

What has already landed:

- Agent session defaults are backfill-only again during run validation; later model/provider selections no longer silently rewrite the session default binding for future resumes.
- `RunTask.data` now carries typed `execution_binding` and standard-runtime `resume_checkpoint` metadata.
- `continue_run` resolves model/runtime identity from stored run metadata first and only uses session defaults as a legacy compatibility fallback.
- `ContinueRunContent` accepts the additive decision surface needed for future Codex approval parity while remaining backward-compatible with legacy `confirmed: bool`.
- `SessionInfo` can now expose additive `runtime_profile` and `runtime_capabilities` fields for reload-safe bootstrap.
- Standard-runtime pause checkpoints now commit before the pause event is emitted, so resumability is no longer advertised ahead of durable host state.
- Codex approval resume now degrades `approve_session` to single-use `accept` when the persisted request did not offer session-wide approval.
- Checkpoint loaders now ignore malformed mixed-version payloads instead of crashing resume flows.
- Focused runtime protocol tests now cover current `experimentalApi` initialization, approval pause/resume, dynamic-tool registration and execution, user-input pause/resume, and malformed checkpoint fallback.
- Codex runtime `add_tool()` now registers host tools as App Server dynamic tools on fresh threads, executes `item/tool/call`, returns `contentItems`, and stops after plan-submission tools when required.
- Codex user-input requests now persist typed checkpoints and emit the same realtime pause shape used by standard-runtime HITL flows.
- Frontend plan-mode routing no longer excludes Codex-backed models, and the HITL confirmation component can send additive approval decisions and generic user-input answers.
- Codex thread and turn request payloads now use protocol-correct App Server JSON values for approval and sandbox settings.
- Codex `acontinue_run()` now matches the standard synchronous async-iterator factory contract consumed by `ContinueRunHandler`.
- Approval response mapping now preserves object-shaped allowed decisions and avoids command-only execpolicy amendment responses for file-change approvals.
- Permissions approval mapping now uses the App Server permissions-profile response shape instead of the command/file `{ decision }` envelope.
- Standard-runtime `continue_run` still falls back to AgentSessionStore when no durable task row exists, while Codex remains strict about typed App Server checkpoints.
- The local Docker sandbox image build now installs the pinned OpenAI Codex CLI package `@openai/codex@0.124.0` instead of an unpinned latest package.
- The E2B sandbox Dockerfile now installs the same pinned OpenAI Codex CLI package instead of the legacy `@intelligent-internet/codex` npm package.
- Runtime capability exposure now disables Codex workflow capabilities when `CODEX_APP_SERVER_WORKFLOWS_ENABLED=false`, when production lacks `CODEX_APP_SERVER_SMOKE_VERIFIED=true`, or when an E2B template has not been smoke-verified.
- `scripts/start.sh` now treats Codex App Server compatibility as a startup preflight surface: Docker images are probed for `codex app-server` plus `initialize.experimentalApi`, and failed local probes disable Codex workflow capabilities for the launched backend instead of leaving Plan UI enabled.
- `uv run pytest -m codex_smoke` now has an opt-in local Docker smoke test that verifies the configured sandbox image exposes `codex app-server` and accepts `initialize` with `experimentalApi`.

Remaining gap:

- Full end-to-end validation against the intended E2B/production sandbox image or template is still required; the local Docker smoke test proves only the configured local Docker image.
- The current `codex_smoke` test verifies App Server availability and `initialize.experimentalApi`, but does not yet exercise authenticated `thread/start.dynamicTools`, `item/tool/call`, approval resume, `item/tool/requestUserInput`, or `mcpServer/elicitation/request` round trips.
- The rollout flag currently gates advertised workflow capabilities and production UI exposure; `CodexRuntimeAgent` still opts into `experimentalApi` when it is invoked.
- The deeper plan-persistence service extraction remains a maintainability follow-up, not a parity blocker.

## Context and Orientation

This work spans frontend routing, realtime orchestration, agent runtime construction,
and Codex transport integration.

Key files in the current implementation:

- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/plan.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/base.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/events/converter.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/plan/milestone.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/plan/suggestion.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/prompts/plan_mode_prompt.py`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/hooks/use-question-handlers.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/question-input.tsx`
- `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/tests/unit/engine/test_codex_runtime_agent.py`

Definitions used in this plan:

- Runtime adapter: the object that turns platform run requests into provider- or runtime-specific execution. Today that is effectively `IIAgent` for most sessions and `CodexRuntimeAgent` for Codex-backed sessions.
- Runtime capability contract: a backend-owned description of what this session runtime can do, for example platform planning, dynamic tool execution, pause/resume, approvals, and user input.
- Workflow orchestration: platform-owned logic for plan generation, milestone persistence, build execution, result progression, and resume handling. This should be independent of the underlying runtime transport.
- Dynamic tool bridge: the Codex App Server path where the server emits `item/tool/call` and the client executes a host-defined tool and returns the result.
- Managed model row: a model-setting row whose execution auth comes from a provider connection instead of a stored API key.
- Execution binding: the durable per-run record of which model setting, runtime profile, runtime setting, and pending resume checkpoint were used for that run.

## Objective Restatement

Define and implement a runtime abstraction that lets Codex-backed agent sessions
participate in the same Plan -> Build -> Result and continue-run workflow contract
as other agent sessions without scattering runtime-specific exclusions across the codebase,
while restoring the original agent-session continuity model from `main`.

## Assumptions

- The parity target is agent-mode sessions, not chat-mode sessions.
- Chat-mode model switching behavior is not the baseline for agent-mode behavior.
- The original agent-mode contract from `main` is the default unless an explicit product decision overrides it.
- Codex App Server experimental APIs are acceptable behind a repo feature flag because the current repo already depends on a bespoke Codex transport.
- The first parity milestone is workflow equivalence, not total equivalence for every tool, connector, or sub-agent behavior.
- Existing realtime event classes remain the canonical frontend contract unless a small additive capability event is needed.
- `Claude Code` does not need the same transport redesign because it is not currently a full runtime replacement in this codebase.
- Existing OpenAI device OAuth and Anthropic OAuth start or complete flows remain unchanged except for additive metadata needed by runtime capabilities or availability display.
- `ProviderConnectionService` remains the only credential authority for provider-backed execution; session and run continuity layers may reference provider connections but must not own OAuth secrets.

Resolved Phase 0 answers:

- Dynamic tools are registered on `thread/start.dynamicTools`; `thread/resume` does not accept a replacement dynamic-tools list in the current primary source.
- Codex plan generation should use the host-executed `submit_plan` dynamic tool in this slice. That keeps the same plan data path as the standard runtime and avoids adding a second structured-output parser.
- `stop_after_tool_call` is preserved by returning the dynamic-tool result to App Server and ending the II-Agent run stream with `RunCompletedEvent` when the host tool marks itself interrupted or stop-after-call.

## Behavior Model

### Intended happy path

1. User opens an agent session and selects any runnable model.
2. Backend resolves a runtime profile for that session, including explicit workflow capabilities.
3. Frontend renders available workflow modes from the capability profile.
4. User submits a first-time website-build request.
5. Workflow orchestration decides the request intent is `plan`.
6. Runtime adapter executes the plan request.
7. Plan result is normalized into the platform `PlanData` shape and persisted through one backend service.
8. Frontend enters the Plan step with milestone data.
9. User triggers Build on one or more milestones.
10. Workflow orchestration dispatches build execution with milestone context through the same runtime adapter.
11. Result events stream through the existing realtime event pipeline and the UI advances to Build and Result.

### Codex-specific happy path after parity work

1. Backend creates a Codex runtime adapter with capabilities resolved up front.
2. During `initialize`, the adapter opts into experimental API support when the feature flag is enabled.
3. On `thread/start` or `thread/resume`, the adapter registers the platform dynamic tools needed for parity.
4. During plan generation, Codex calls `submit_plan` through the dynamic tool bridge.
5. II-Agent persists the plan through the canonical plan service and publishes the same plan event used by other runtimes.
6. If Codex requests approval or user input, the adapter converts it into the same `RunPausedEvent` shape consumed by the frontend.
7. User sends `continue_run`; backend resolves the pending request and the Codex adapter answers the underlying App Server request instead of hard failing.

### Failure scenarios to handle explicitly

- Runtime does not advertise or successfully enable required experimental features.
  Result: session capability profile must degrade before the user enters the flow, not after the prompt is sent.

- Dynamic tool bridge partially works but a required workflow tool is missing.
  Result: fail the run with a typed capability error, not freeform fallback prose.

- Codex thread resumes without the same dynamic tools or capability set as the original run.
  Result: treat as stale runtime binding, re-register tools, and resume only after the bridge state is reconciled.

- Plan result is malformed or incomplete.
  Result: canonical plan persistence rejects it with a typed validation error and emits a structured run failure.

## State Model

### Runtime capability states

- `undetermined`: session has a selected model but no resolved runtime profile yet.
- `resolved`: backend resolved the runtime profile and capabilities.
- `degraded`: runtime is runnable but lacks one or more workflow capabilities; frontend must hide or disable dependent workflow features.
- `ready`: runtime supports the required workflow capabilities for this session.

Invariant:

- Frontend never guesses workflow availability when capability state is not `resolved`.

### Workflow run states

- `intent_selected`: backend classified the user action as `plan`, `build`, `modify_plan`, or `continue`.
- `runtime_bound`: workflow request is bound to a specific runtime adapter instance and capability profile.
- `executing`: runtime is producing deltas, tool calls, or reasoning.
- `paused`: runtime is awaiting approval or user input.
- `completed`: run succeeded and any workflow-side persistence finished.
- `failed`: run failed before or after persistence.

Invariants:

- Plan persistence is separate from runtime completion. A run can finish, but plan persistence must still succeed for the workflow step to count.
- A paused run must carry enough host-side checkpoint state to answer the exact pending request on resume.

### Session continuity invariants

- Existing agent sessions and projects must survive global model or provider selection changes without silently rebinding their execution identity.
- A run resumes against the execution binding captured when that run started, not against whatever model or runtime the session currently resolves to later.
- Explicit model or runtime changes for an agent workflow happen through one of two product actions only:
  - start a new session or fork
  - execute an explicit session rebind flow that updates the session default for future runs only
- Provider disconnect or reauth does not delete the durable model identity needed to explain or recover an existing session. It only changes availability.

### OAuth compatibility invariants

- OpenAI Codex device-code login and Claude Code OAuth continue to persist credentials through the current MCP service entry points.
- `ProviderConnectionService.upsert_connection(...)` remains the single write authority for provider-backed credentials.
- Runtime parity work may read provider connection ids and derived availability, but it must not duplicate or fork OAuth-secret storage into session metadata, run metadata, or frontend state.
- Provider reconnect or token refresh may update credential material and availability, but it must not rewrite existing agent run bindings or delete the durable identity referenced by sessions, forks, or run checkpoints.

## Proposed Design

### 1. Introduce a backend runtime capability contract

Add a small runtime profile layer, for example:

- `RuntimeCapabilities`
- `RuntimeProfile`
- `RuntimeProfileResolver`

Suggested fields:

- `supports_platform_plan`
- `supports_platform_plan_modification`
- `supports_pause_resume`
- `supports_approvals`
- `supports_user_input`
- `supports_dynamic_tools`
- `supports_connector_injection`
- `supports_sub_agents`
- `supports_persistent_threads`

This resolver should live near runtime construction, not in the frontend. It should
derive capabilities from model config, runtime product, feature flags, and runtime
transport implementation.

### 2. Split workflow orchestration from transport

Create a platform workflow service that owns:

- run intent classification (`plan`, `build`, `modify_plan`, `continue`)
- plan persistence
- milestone context generation
- workflow-specific validation
- resume checkpoint resolution

This service becomes the shared entry point used by current `query.py`, `plan.py`,
and `continue_run.py`. Those handlers should become thin protocol shims, or eventually
collapse into one command handler plus explicit intent.

### 3. Restore the original continuity seam with explicit execution bindings

Add a host-owned `RunExecutionBinding` model resolved at run start and persisted in
`RunTask.data` through a small `RunCheckpointService`.

Required fields:

- `model_setting_id`
- `resolved_model_id`
- `provider`
- `credential_source`
- `provider_connection_id`
- `runtime_product`
- `mcp_setting_id`
- `runtime_capabilities`
- `resume_checkpoint`

Storage authority:

- `RunTask.data.execution_binding` becomes the authoritative index for per-run execution identity.
- `RunTask.data.resume_checkpoint` becomes the authoritative host-side metadata index for pending resume state.
- Standard `IIAgent` resume can keep using `AgentSessionStore` for paused `RunOutput` payloads initially, but `RunCheckpointService` must register a reference to that checkpoint so `continue_run` stops inferring runtime identity from `SessionInfo`.
- Codex resume stores its pending App Server request metadata in the same `RunCheckpointService` surface instead of inventing a parallel store.

Typed checkpoint contract:

- `execution_binding.version = 1`
- `resume_checkpoint.version = 1`
- standard-runtime checkpoint shape:
  - `kind = "standard_agent"`
  - `run_id`
  - `session_store_backend = "agent_session_store"`
  - `paused_output_ref = { run_id, session_id }`
  - `pending_tool_ids`
  - `pause_reason`
- Codex checkpoint shape:
  - `kind = "codex_app_server"`
  - `thread_id`
  - `turn_id`
  - `pending_request_id`
  - `pending_request_kind = "approval" | "user_input"`
  - `request_payload`
  - `allowed_decisions`
  - `registered_tool_fingerprint`
  - `pause_reason`

Write timing and mutation authority:

- `RunCheckpointService` writes `execution_binding` immediately after model and runtime resolution and before the runtime adapter starts streaming.
- pause handlers update `resume_checkpoint` before any `RunPausedEvent` is emitted to the frontend.
- `continue_run` reads only through `RunCheckpointService`; direct reads from mutable session defaults are treated as a bug after Phase 0.
- if checkpoint persistence fails, the run fails closed before advertising resumability.

Legacy compatibility:

- standard-runtime paused runs created before this rollout may continue using the existing `AgentSessionStore` plus pinned session fallback for one compatibility window when `execution_binding` is absent.
- Codex paused-run backward compatibility is not required because Codex `continue_run` is already unsupported in the current product.
- remove the standard-runtime fallback only after one release cycle and after production confirms all active paused runs carry `execution_binding`.

Session semantics:

- Restore `session.model_setting_id` backfill-only behavior for agent sessions.
- Do not rewrite `session.model_setting_id` or `session.mcp_setting_id` on every run.
- If the product later wants "switch model for this agent session", implement that as an explicit rebind command that updates session defaults for future runs only.

### 4. Replace runtime identity branching with runtime adapters

Define a runtime adapter protocol with methods roughly like:

- `run(request: RuntimeRunRequest) -> AsyncIterator[RunOutputEvent]`
- `resume(request: RuntimeResumeRequest) -> AsyncIterator[RunOutputEvent]`
- `get_capabilities() -> RuntimeCapabilities`
- `bind_workflow_tools(...)`

Implementations:

- `StandardAgentRuntimeAdapter` wrapping `IIAgent`
- `CodexAppServerRuntimeAdapter` wrapping the current Codex transport

The factory should return a runtime adapter plus capabilities, not just a raw agent object.

### 5. Make plan persistence runtime-neutral

Today, plan mode depends on `MilestoneTool` mutating session metadata directly.
That is the wrong seam.

Refactor to:

- define a canonical `PlatformPlan` schema
- persist plans only through a `PlanPersistenceService`
- let runtimes produce a `PlatformPlan` through one of two strategies:
  - `tool_submission`: standard agent calls `submit_plan`
  - `runtime_bridge_submission`: Codex dynamic tool bridge calls `submit_plan`

Both strategies must end in the same persistence path and publish the same plan event.

### 6. Implement a Codex dynamic tool bridge

Use the documented App Server path instead of returning failure for `item/tool/call`.

Concrete changes:

- opt into `experimentalApi` during `initialize`
- stop hardcoding `approvalPolicy: "never"` for sessions that advertise approval parity
- register workflow-critical dynamic tools on `thread/start` and `thread/resume`
- route `item/tool/call` into platform tool execution
- return structured tool results to App Server

Semantic requirement:

- Workflow submission tools such as `submit_plan` and `submit_plan_modification_suggestions` must preserve current `stop_after_tool_call` behavior. If App Server has no native stop-after-tool primitive, the host bridge must terminate the turn immediately after accepted workflow submission instead of letting Codex continue freeform output.

Initial Codex parity tool set should be intentionally narrow:

- `submit_plan`
- `submit_plan_modification_suggestions`
- any workflow-owned resume/approval helpers needed for pause/resume parity

Do not try to mirror every existing II-Agent tool on day one.

### 7. Implement approval and user-input parity for Codex

Current behavior cancels approval and user-input requests automatically.
That needs to become a host-side pause bridge.

Concrete changes:

- map App Server approval requests into `RunPausedEvent` requirements
- map `tool/requestUserInput` into the same user-input schema surface used by existing runtime pauses
- persist the unresolved request id and enough thread/turn context to answer it later
- implement `continue_run` by resolving the stored pending App Server request instead of rejecting Codex runs

Protocol changes:

- expand `ContinueRunContent` from binary `confirmed: bool` into an additive decision surface:
  - `decision`: `approve_once | approve_session | reject | cancel`
  - `user_input`
  - `policy_patch` (optional additive execution-policy adjustments)
- keep the old boolean field only as a backward-compatible alias for standard yes or no pauses until the frontend migrates
- expand the confirmation UI from binary confirm or reject to the same decision set above

Resume routing:

- `continue_run` must load `RunExecutionBinding` first
- standard runtime resumes through the existing paused-tool path referenced by the checkpoint
- Codex runtime resumes by answering the stored App Server pending request from the same checkpoint service

### 8. Expose capabilities to the frontend and remove runtime-product gates

Frontend should receive capability data from the backend through `SessionInfo`
bootstrap as the authoritative reload-safe source. A separate realtime
`session.runtime.updated` event is only used when an explicit session rebind
changes future-run defaults. Then:

- add additive `SessionInfo` fields for `runtime_profile` and `runtime_capabilities`
- fetch session details before replaying session events on enter or reload
- hydrate capability state from `SessionInfo` first, then apply replayed events, then reconcile with `run_status`
- treat `session.runtime.updated` as an override for future-run defaults only; it must not mutate any active `RunExecutionBinding`

- build mode availability is filtered from capabilities
- first-turn workflow routing uses capabilities plus request intent
- Codex is no longer special-cased in `question-input.tsx` or `use-question-handlers.tsx`

### 9. Preserve the existing realtime event contract

The current converter and `process_agent_event_stream()` path are usable.
Do not redesign the frontend event model unless necessary.

Instead:

- make Codex emit proper `RunPausedEvent`, `ToolCallStartedEvent`, and `ToolCallCompletedEvent`
- keep `convert_agent_event_to_realtime()` as the normalization seam

## Risks and Failure Modes

- Experimental API risk: dynamic tools are gated by `experimentalApi`. A server upgrade or mismatch could break the bridge.
  Mitigation: guard with a backend feature flag and protocol smoke tests in CI.

- Over-abstraction risk: building a grand runtime framework before landing parity could stall the work.
  Mitigation: phase the contract narrowly around workflow parity first.

- Duplicate-tool risk: Codex already has native shell and file tools. Exposing overlapping II-Agent tools too early may create conflicting behavior.
  Mitigation: first expose only workflow-owned dynamic tools that Codex lacks natively.

- Resume-checkpoint drift: if pending App Server request ids are not stored reliably, `continue_run` will remain flaky even after the frontend is enabled.
  Mitigation: add explicit pending-request persistence and resume tests.

- Billing drift: Codex-hosted tool executions need to flow through the same billing semantics if they incur direct costs.
  Mitigation: keep runtime tool bridge executions emitting normal tool events through the shared event processor.

- Continuity drift: if agent sessions keep mutating `session.model_setting_id` and `session.mcp_setting_id` on each run, the new resume bridge will still be racy.
  Mitigation: restore backfill-only session binding and move exact run identity to `RunExecutionBinding`.

- Catalog-identity drift: if provider-managed rows continue to be deleted on disconnect, reconnect and session recovery will remain brittle.
  Mitigation: mark managed rows unavailable instead of deleting them, or move session identity off those rows.

## Alternatives and Tradeoffs

### Alternative A: keep Codex excluded and improve the fallback copy

Rejected. This is process theater. It preserves the broken abstraction and guarantees the same class of regressions later.

### Alternative B: parse freeform Codex responses into plans without dynamic tools

Possible as a temporary bootstrap, but brittle. It replaces explicit tool contracts with prompt parsing and weakens modification flows and validation.

### Alternative C: force Codex sessions back onto standard `IIAgent`

Rejected. That discards the reason Codex was integrated as a runtime in the first place and ignores the documented App Server capabilities that can support the platform workflow.

### Alternative D: bridge only plan mode and keep `continue_run` unsupported

Rejected. The user problem is not "generate milestones once"; it is parity of the actual agentic harness. A plan-only patch would still break the same user journey at the first approval or input request.

### Alternative E: let agent sessions freely switch providers and runtimes mid-thread

Rejected as the default. That is a business-logic change from `main`, not a harmless refactor. If product wants it later, it needs an explicit session-rebind UX plus per-run execution binding so paused runs and project continuity stay coherent.

## Critical Review

The first version of this design risks being too clean on paper and too broad in practice.

Weaknesses:

- It assumes the current `BaseAgentTool` model can be reused directly through a Codex host bridge. That may be false for some tools that depend on deep `IIAgent` internals.
- It pushes significant responsibility into a new workflow layer. If that layer is introduced without disciplined boundaries, it can become a second god-object next to the handlers.
- It depends on experimental Codex APIs. That is a real operational risk, not a footnote.

What breaks first if we get the sequencing wrong:

- If we ship frontend capability logic before resume and tool bridging are real, we will expose Plan mode for Codex again and repeat the same failure with better branding.
- If we expose too many dynamic tools too early, Codex runs will behave unpredictably and debugging will be painful.
- If we refactor plan persistence and runtime construction in one giant patch, reviewability will collapse.
- If we do not restore the original session continuity contract first, every resume fix will be built on top of shifting sand.

## Revised Design

The implementation should be incremental and biased toward bounded seams:

1. Restore session continuity semantics and add `RunExecutionBinding` first, without changing frontend workflow behavior.
2. Add `RuntimeCapabilities` and a resolver second.
3. Add protocol-level Codex smoke tests for `experimentalApi`, approvals, dynamic tools, and user input before large runtime refactors.
4. Extract plan persistence behind one service before changing how Codex submits plans.
5. Implement a narrow Codex dynamic tool bridge for `submit_plan` and plan-modification suggestions only.
6. Implement Codex approval and user-input bridging plus `continue_run`.
7. Move frontend routing to capability-driven behavior only after backend parity works.
8. Expand beyond workflow-critical parity after the user journey is proven stable.

This version is less elegant than "full runtime framework first," but it is much more likely to ship correctly.

## Plan of Work

### Phase 0: continuity restoration and protocol spike

Status after review: continuity restoration, execution binding persistence, standard and Codex checkpoint storage, approval resume, and focused runtime protocol tests are in repo. Remaining Phase 0 work is pinned App Server request-shape capture plus OAuth persistence regression coverage.

- Refactor `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/sessions/service.py`
  so agent sessions stop rewriting `model_setting_id` and `mcp_setting_id` on every run.
- Add a `RunCheckpointService` that persists `RunExecutionBinding` and pending
  resume metadata into `RunTask.data`.
- Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
  to load runtime identity from `RunExecutionBinding`, not from current session state.
- Define typed schema helpers for `RunTask.data.execution_binding` and `RunTask.data.resume_checkpoint` instead of leaving them as anonymous dict blobs.
- Implement the one-release compatibility fallback for legacy paused standard-runtime runs that lack `execution_binding`.
- Add focused regression tests around `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/mcp/service.py`
  and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/settings/provider_connections/service.py`
  proving that Codex OpenAI device OAuth and Claude Code OAuth still end in the same provider-connection and MCP-setting persistence paths.
- Add focused tests around `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py` to verify:
  - `initialize` with `experimentalApi`
  - dynamic tool request handling
  - approval request handling
  - tool user-input request handling
- Add focused regression tests proving that changing the selected model or provider
  after a run starts does not change the execution binding used by `continue_run`.
- Record the exact request and response payloads needed by the pinned Codex sandbox image.

### Phase 1: runtime capability contract

- Add a new backend module for runtime profiles and capabilities.
- Extend `SessionInfo` and session-detail APIs with additive runtime capability fields.
- Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py` to resolve runtime profiles centrally.
- Surface capabilities through `SessionInfo` bootstrap and an additive
  `session.runtime.updated` realtime event for explicit rebinds only.

### Phase 2: workflow orchestration extraction

- Create a workflow service that centralizes plan/build/continue intent handling.
- Refactor `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py`
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/plan.py`
  and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
  to use the shared workflow layer.
- Introduce canonical plan persistence so `MilestoneTool` becomes a submission mechanism, not the persistence owner.
- Stop deleting provider-managed model rows during catalog sync when they are merely unavailable; mark them unavailable and preserve durable identity.

### Phase 3: Codex workflow bridge

- Refactor `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py` into a runtime adapter with:
  - experimental API opt-in
  - dynamic tool registration
  - tool-call execution bridge
  - pause request capture
  - resume request resolution
- Replace hardcoded `approvalPolicy: "never"` with policy selected from runtime capabilities and session settings.
- Preserve existing thread persistence and event streaming behavior.

### Phase 4: frontend capability adoption

- Add a real frontend test runner and scripts (`vitest` plus React Testing Library) before relying on UI/state regression coverage.
- Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/hooks/use-question-handlers.tsx`
  and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/question-input.tsx`
  so workflow availability comes from capabilities instead of `runtime_product`.
- Update session-entry and replay flows so session details bootstrap loads before event replay.
- Ensure first-turn website build routing uses workflow intent plus capabilities.
- Expand the continue UI from binary approval to the new additive decision contract.

### Phase 5: hardening and rollout

- Add regression coverage for:
  - OpenAI Codex device OAuth and Claude Code OAuth happy paths still persist usable provider connections and runtime settings
  - first-turn Codex website build -> plan generation
  - Codex modify-plan suggestions and modify-plan submission
  - Codex milestone build execution
  - Codex approval pause -> continue_run
  - session reload followed by plan/build/result continuation
  - session reload followed by paused Codex resume
  - changing selected model or provider while an existing agent session remains bound to its prior execution context
  - chat session continuation while switching to another selectable model remains request-scoped and does not mutate agent-session bindings
  - non-Codex regression coverage for the same flows
- Remove the Codex-specific plan and continue hard rejections once parity is proven.

## Validation and Acceptance

Behavioral acceptance criteria:

- A Codex-backed `WEBSITE_BUILD` session can generate a persisted project plan and the UI enters the Plan step.
- A Codex-backed session can request plan-modification suggestions and submit a modified plan through the same persisted plan contract.
- A Codex-backed session can build one milestone or all milestones and milestone statuses update through the existing plan event path.
- A Codex-backed session can pause for approval or user input and successfully resume through `continue_run`.
- Reloading the session preserves runtime capabilities, plan state, and paused-run recovery behavior.
- Changing the globally selected model or provider does not change the execution binding of an existing agent session or paused run unless the user performs an explicit rebind or new-session action.
- Mixed-version deployment is safe: backend accepts both legacy and additive `continue_run` payloads during rollout, and legacy paused standard-runtime runs remain resumable for the compatibility window.
- Existing Codex OpenAI device OAuth and Claude Code OAuth flows still create or update the same provider-connection and MCP-setting records used today.
- Chat sessions can continue across model switches exactly as before because chat model choice remains request-scoped rather than session-bound.
- Non-Codex sessions continue to use the same workflow with no regression in plan generation, milestone execution, or pause/resume.
- No frontend workflow gating depends directly on `runtime_product === "codex"`.
- No backend workflow handler rejects Codex by name for plan or continue flow.

Suggested validation commands after implementation:

- `uv run python -m py_compile src/ii_agent/agents/codex_runtime.py src/ii_agent/realtime/handlers/base.py src/ii_agent/realtime/handlers/continue_run.py src/ii_agent/realtime/schemas.py`
- `uv run ruff check --fix-only <changed_python_files>`
- `uv run ruff format <changed_python_files>`
- `uv run ruff check <changed_python_files>`
- `uv run ruff format --check <changed_python_files>`
- `uv run pytest src/tests/unit/tasks/test_run_checkpoint_service.py src/tests/unit/realtime/test_base_handler_process_stream.py src/tests/unit/engine/test_codex_runtime_agent.py src/tests/unit/sessions/test_session_runtime_selection.py src/tests/unit/realtime/test_socket_handlers_r4.py::TestContinueRunHandlerHandle`
- `uv run pytest src/tests/unit/settings/test_mcp_setting_service.py::test_poll_codex_openai_device_oauth_persists_codex_setting src/tests/unit/settings/test_mcp_service_deep.py::test_complete_claude_code_oauth_serializes_uuid_provider_connection_id_for_storage src/tests/unit/settings/test_provider_connection_service.py::test_upsert_connection_updates_existing_row src/tests/unit/settings/test_provider_connection_service.py::test_upsert_connection_encrypts_and_lists`
- `npm exec tsc -- --noEmit` from `frontend/`
- `npm exec eslint -- src/components/agent/tool-confirmation.tsx src/components/question-input.tsx src/hooks/use-question-handlers.tsx src/typings/agent.ts --report-unused-disable-directives --max-warnings 0` from `frontend/`

Expected results:

- All targeted tests pass.
- TypeScript compile and targeted lint for changed frontend files pass.
- Full sandbox E2E remains a release validation item until the intended OpenAI Codex CLI image is available.

## Production-Grade Automated Test Strategy

The minimum credible suite is a layered test matrix. Backend-only coverage is not enough
because the parity failure crossed runtime transport, realtime protocol, replay logic,
and UI state restoration.

### Suite 1: backend unit and contract tests

These should run on every PR and stay fast.

- `SessionService.validate_and_prepare_for_run(...)`
  - agent sessions backfill missing `model_setting_id` and `mcp_setting_id` once
  - later global model or provider selection changes do not rewrite existing agent-session defaults
  - chat sessions remain unaffected by the agent continuity rules
- `RunCheckpointService`
  - writes `RunTask.data.execution_binding`
  - writes `RunTask.data.resume_checkpoint`
  - stores a standard-runtime checkpoint reference when paused state still lives in `AgentSessionStore`
  - stores a Codex pending-request checkpoint without depending on `SessionInfo`
- `ContinueRunHandler`
  - loads `RunExecutionBinding` before resolving runtime identity
  - standard runtime resume uses checkpoint indirection rather than mutable session state
  - Codex resume answers the stored App Server request instead of hard rejecting
  - legacy `confirmed: bool` remains backward-compatible
  - new additive decision payload supports `approve_once`, `approve_session`, `reject`, and `cancel`
  - `policy_patch` is forwarded only to runtimes that support it
- `CodexRuntimeAgent` or `CodexAppServerRuntimeAdapter`
  - `initialize` opts into `experimentalApi`
  - approval policy is capability-driven rather than hardcoded to `never`
  - dynamic tool registration occurs on `thread/start`
  - thread reuse is gated by registered dynamic-tool fingerprint because `thread/resume` cannot add dynamic tools
  - `item/tool/call` maps to workflow-owned tool execution
  - `tool/requestUserInput` maps to the pause contract
  - approval requests map to the pause contract
  - successful `submit_plan` and `submit_plan_modification_suggestions` preserve `stop_after_tool_call` semantics
  - resume works after a persisted pending-request checkpoint is restored
- `PlanPersistenceService` or workflow service
  - `plan`, `modify_plan_suggestions`, and `modify_plan` all normalize to one persisted plan contract
  - malformed plan payloads fail with typed validation errors
- provider-backed model and OAuth services
  - existing OpenAI Codex device OAuth and Claude Code OAuth persistence paths remain unchanged
  - provider reconnect or expiry changes availability, not durable identity
  - managed model rows are marked unavailable instead of being deleted when continuity depends on them

### Suite 2: handler and realtime integration tests

These should still run in CI on every PR, but may use a fake runtime adapter and real handler wiring.

- `query`, `plan`, and `continue_run` handlers share one workflow intent boundary
- first-turn `WEBSITE_BUILD` routes to `plan` when capabilities allow it
- Codex plan flow emits the same `plan.milestone.generated` event shape as standard runtime
- Codex modify-plan suggestions emit the same `plan.modification.options` event shape as standard runtime
- paused-run resume restores the correct run after session reload
- realtime/session bootstrap includes authoritative runtime capabilities
- additive `session.runtime.updated` only appears for explicit session rebinds
- replayed session events plus `run_status` reconcile to the same final UI state as live streaming

### Suite 3: frontend state and reducer or hook tests

These are currently missing in practice and need a real harness. Add `vitest` plus React Testing Library before implementation goes far.

- `use-question-handlers.tsx`
  - capability-driven routing selects `plan`, `modify_plan`, or `build` correctly
  - first-turn website build auto-enters Plan only when capabilities allow it
  - global selected model changes do not silently alter active agent-session bindings
- `question-input.tsx`
  - available build modes are filtered from capabilities, not `runtime_product`
  - Codex-backed sessions show Plan Mode only when backend capabilities advertise it
- `tool-confirmation.tsx`
  - renders binary legacy flow for standard pauses
  - renders expanded decision UI for Codex approval parity
  - submits the correct websocket payload for `approve_once`, `approve_session`, `reject`, and `cancel`
- `use-session-manager.tsx`
  - replay path restores `run_id`, `session_id`, plan data, and run status correctly
  - replay of paused sessions preserves enough state to resume correctly
- `use-session-enter.tsx`
  - reload restores cached plan state, modification options, and build step
  - invalid cached `PLAN` state without plan data falls back safely
- `use-app-events.tsx`
  - plan generation updates store and build step
  - modify-plan suggestion events update store and assistant messages
  - milestone update events reconcile status after live or replayed events

### Suite 4: browser end-to-end tests

Add Playwright browser flows with mocked provider/runtime backends or a deterministic fake runtime.
These should run on merge to main and before release, not necessarily on every inner-loop save.

- new Codex-backed website-build session: prompt -> Plan -> Build -> Result
- modify-plan suggestions flow: request suggestions -> choose change -> submit modified plan
- paused approval flow: agent pauses -> user approves once -> run resumes
- paused user-input flow: agent pauses -> user submits input -> run resumes
- reload during paused run: refresh page -> session rehydrates -> continue works
- reload after plan generation: refresh page -> plan UI restores without duplicate event side effects
- chat session switches models mid-thread without losing history
- switching global model while an agent session exists does not rebind the active project session

### Suite 5: protocol and smoke tests against the pinned Codex runtime

These are the earliest warning for App Server drift and should be required in CI for branches touching Codex transport.

- bootstrap command still starts the pinned App Server image
- `initialize` returns experimental API support when expected
- `thread/start` and `thread/resume` accept the registered tool shape
- approval request payloads match the resume bridge parser
- user-input request payloads match the pause bridge parser
- tool-call result submission shape remains compatible
- failure mode for unsupported experimental API degrades capabilities instead of surfacing broken Plan UI

### CI tiers

- PR required
  - backend unit and contract tests
  - handler and realtime integration tests
  - frontend vitest suite
  - frontend build
- merge or release required
  - Playwright end-to-end flows
  - pinned Codex protocol smoke tests
  - full `uv run pytest`

### Concrete repo changes needed before this strategy is real

- add an actual frontend test runner and scripts; the current frontend README mentions `pnpm test`, but `frontend/package.json` does not define it
- add dedicated test modules instead of burying new parity tests in unrelated billing-focused files
- add deterministic fake runtime adapters and websocket fixtures so the end-to-end suite does not depend on live provider services
- keep the protocol-smoke layer separate from broad end-to-end UI tests so App Server drift is diagnosed quickly

## Release Sequencing

Roll this out in additive stages. Do not ship the new frontend assumption before the backend contract exists.

1. Backend additive deploy:
   - add `RunExecutionBinding`
   - add `RunCheckpointService`
   - extend `ContinueRunContent` parser to accept both legacy and additive payloads
   - extend `SessionInfo` with additive runtime capability fields
   - keep Codex capability flags disabled in the UI
2. Frontend compatibility deploy:
   - consume `SessionInfo.runtime_capabilities`
   - fetch session details before event replay
   - support expanded continue-run decisions while remaining compatible with legacy binary pauses
3. Capability enablement:
   - enable Codex plan capabilities only after protocol smoke tests, backend parity tests, and frontend replay tests are green
4. Cleanup:
   - remove legacy standard-runtime resume fallback after the compatibility window
   - remove direct `runtime_product === "codex"` gates after capability-driven behavior is fully live

## Idempotence and Recovery

- Capability-contract work is additive first; it can ship behind a backend feature flag without immediately enabling Codex plan mode in the UI.
- Dynamic tool bridging must be feature-flagged so the repo can fall back to the current Codex transport if protocol assumptions fail in production.
- Remove hard rejections in `plan.py` and `continue_run.py` only after the Codex bridge tests are green.
- If resume bridging proves unstable, keep the new capability contract and plan persistence refactor, but leave Codex `supports_pause_resume = false` until the pending-request storage is correct.
- If product declines explicit session rebinding and insists on free mid-thread agent-session switching, add that as a separate follow-up because it needs its own UX, migration rules, and recovery semantics.

## Business Logic Decisions Needed

- Recommended default: keep the original `main` behavior for agent mode. Model or provider changes in the global selector affect new sessions or explicit forks, not the currently open agent session.
- Optional future divergence: add an explicit "switch this agent session to model X" action. If adopted, it must:
  - update session defaults only for future runs
  - preserve existing run execution bindings for resume
  - emit `session.runtime.updated` so reload and live state stay aligned
- Do not treat provider disconnect or OAuth expiry as permission to delete the model identity referenced by historical sessions. Availability may change; identity must not.

## Sources

- Repo implementation:
  - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py`
  - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/plan.py`
  - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
  - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/tools/plan/milestone.py`
  - `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/events/converter.py`
- Official Codex App Server references:
  - [App Server – Codex | OpenAI Developers](https://developers.openai.com/codex/app-server)
  - [Unlocking the Codex harness: how we built the App Server | OpenAI](https://openai.com/index/unlocking-the-codex-harness/)

Plan revision note (2026-04-24 01:40Z): updated the plan after validating the landed backend slices against repo reality. The revision records the checkpoint-ordering, approval-decision, and mixed-version parsing gaps found during review, marks the new targeted protocol tests as landed, and narrows the remaining Phase 0 work to request-shape capture plus OAuth persistence coverage.
