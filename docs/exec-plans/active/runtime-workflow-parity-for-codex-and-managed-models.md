# Runtime Workflow Parity For Codex And Managed Model Sessions

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

## Purpose / Big Picture

After this effort, users should be able to pick any runnable agent-mode model session
including Codex-backed sessions and get the same platform workflow semantics:
plan generation, milestone-based build execution, result delivery, pause/resume, and
approval or input handling. The platform must stop encoding workflow behavior as
"whatever the current runtime happens to support by accident."

Observable outcomes after implementation:

- First-turn website build prompts enter the same platform Plan -> Build -> Result
  journey for Codex-backed and non-Codex-backed sessions.
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
- [ ] Implement Phase 0 capability inventory and protocol spike tests for Codex App Server experimental APIs.
- [ ] Implement Phase 1 backend runtime capability contract and expose it to the frontend session flow.
- [ ] Implement Phase 2 workflow orchestration extraction so plan/build/result semantics are platform-owned instead of handler- or runtime-owned.
- [ ] Implement Phase 3 Codex runtime bridge for dynamic tools, approvals, and user-input requests.
- [ ] Implement Phase 4 Codex plan and continue parity on top of the new contracts.
- [ ] Implement Phase 5 frontend capability-driven workflow selection and remove runtime-product gating.
- [ ] Execute the release validation set and close remaining parity gaps.

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

## Decision Log

- Decision: parity work will target runtime-backed session behavior, not model-family branding.
  Rationale: `runtime_product` is currently acting as both selector and feature gate. That conflation is the design bug.
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

## Outcomes & Retrospective

Planning only so far. No implementation has landed from this ExecPlan yet.

What is already clarified:

- The current failure is architectural, not a single bug.
- Codex App Server can support the required interaction patterns if II-Agent bridges them correctly.
- The right abstraction is "workflow capabilities over runtime adapters," not "special-case Codex in each handler."

Remaining gap:

- The repo still contains hard runtime exclusions and no shared capability contract.
- Codex transport still does not opt into or bridge experimental App Server features.
- Plan mode remains coupled to injected tools and direct session-metadata mutation.

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
- Managed model session: a session backed by provider-managed runtime credentials or runtime products, such as Codex or Claude Code backed model rows.

## Objective Restatement

Define and implement a runtime abstraction that lets Codex-backed agent sessions
participate in the same Plan -> Build -> Result and continue-run workflow contract
as other agent sessions without scattering runtime-specific exclusions across the codebase.

## Assumptions

- The parity target is agent-mode sessions, not chat-mode sessions.
- Codex App Server experimental APIs are acceptable behind a repo feature flag because the current repo already depends on a bespoke Codex transport.
- The first parity milestone is workflow equivalence, not total equivalence for every tool, connector, or sub-agent behavior.
- Existing realtime event classes remain the canonical frontend contract unless a small additive capability event is needed.
- `Claude Code` does not need the same transport redesign because it is not currently a full runtime replacement in this codebase.

Unresolved questions to answer during Phase 0:

- Which exact Codex App Server requests and fields are required to register dynamic tools on `thread/start` and `thread/resume` in the version pinned by the sandbox image?
- Whether plan-generation for Codex should use a host-executed `submit_plan` dynamic tool immediately, or whether the first release should parse a strictly structured final output and only add dynamic tools for resume and approvals.
- Whether Codex turn history can safely be the single source of truth for resume, or whether II-Agent still needs its own run checkpoint object for deterministic continuation.

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

### 3. Replace runtime identity branching with runtime adapters

Define a runtime adapter protocol with methods roughly like:

- `run(request: RuntimeRunRequest) -> AsyncIterator[RunOutputEvent]`
- `resume(request: RuntimeResumeRequest) -> AsyncIterator[RunOutputEvent]`
- `get_capabilities() -> RuntimeCapabilities`
- `bind_workflow_tools(...)`

Implementations:

- `StandardAgentRuntimeAdapter` wrapping `IIAgent`
- `CodexAppServerRuntimeAdapter` wrapping the current Codex transport

The factory should return a runtime adapter plus capabilities, not just a raw agent object.

### 4. Make plan persistence runtime-neutral

Today, plan mode depends on `MilestoneTool` mutating session metadata directly.
That is the wrong seam.

Refactor to:

- define a canonical `PlatformPlan` schema
- persist plans only through a `PlanPersistenceService`
- let runtimes produce a `PlatformPlan` through one of two strategies:
  - `tool_submission`: standard agent calls `submit_plan`
  - `runtime_bridge_submission`: Codex dynamic tool bridge calls `submit_plan`

Both strategies must end in the same persistence path and publish the same plan event.

### 5. Implement a Codex dynamic tool bridge

Use the documented App Server path instead of returning failure for `item/tool/call`.

Concrete changes:

- opt into `experimentalApi` during `initialize`
- register workflow-critical dynamic tools on `thread/start` and `thread/resume`
- route `item/tool/call` into platform tool execution
- return structured tool results to App Server

Initial Codex parity tool set should be intentionally narrow:

- `submit_plan`
- `submit_plan_modification_suggestions`
- any workflow-owned resume/approval helpers needed for pause/resume parity

Do not try to mirror every existing II-Agent tool on day one.

### 6. Implement approval and user-input parity for Codex

Current behavior cancels approval and user-input requests automatically.
That needs to become a host-side pause bridge.

Concrete changes:

- map App Server approval requests into `RunPausedEvent` requirements
- map `tool/requestUserInput` into the same user-input schema surface used by existing runtime pauses
- persist the unresolved request id and enough thread/turn context to answer it later
- implement `continue_run` by resolving the stored pending App Server request instead of rejecting Codex runs

### 7. Expose capabilities to the frontend and remove runtime-product gates

Frontend should receive capability data from the backend on session bootstrap or an
added session/runtime event. Then:

- build mode availability is filtered from capabilities
- first-turn workflow routing uses capabilities plus request intent
- Codex is no longer special-cased in `question-input.tsx` or `use-question-handlers.tsx`

### 8. Preserve the existing realtime event contract

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

## Alternatives and Tradeoffs

### Alternative A: keep Codex excluded and improve the fallback copy

Rejected. This is process theater. It preserves the broken abstraction and guarantees the same class of regressions later.

### Alternative B: parse freeform Codex responses into plans without dynamic tools

Possible as a temporary bootstrap, but brittle. It replaces explicit tool contracts with prompt parsing and weakens modification flows and validation.

### Alternative C: force Codex sessions back onto standard `IIAgent`

Rejected. That discards the reason Codex was integrated as a runtime in the first place and ignores the documented App Server capabilities that can support the platform workflow.

### Alternative D: bridge only plan mode and keep `continue_run` unsupported

Rejected. The user problem is not "generate milestones once"; it is parity of the actual agentic harness. A plan-only patch would still break the same user journey at the first approval or input request.

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

## Revised Design

The implementation should be incremental and biased toward bounded seams:

1. Add `RuntimeCapabilities` and a resolver first, without changing workflow behavior.
2. Add protocol-level Codex smoke tests for `experimentalApi`, approvals, dynamic tools, and user input before large runtime refactors.
3. Extract plan persistence behind one service before changing how Codex submits plans.
4. Implement a narrow Codex dynamic tool bridge for `submit_plan` and plan-modification suggestions only.
5. Implement Codex approval and user-input bridging plus `continue_run`.
6. Move frontend routing to capability-driven behavior only after backend parity works.
7. Expand beyond workflow-critical parity after the user journey is proven stable.

This version is less elegant than "full runtime framework first," but it is much more likely to ship correctly.

## Plan of Work

### Phase 0: capability and protocol spike

- Add focused tests around `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py` to verify:
  - `initialize` with `experimentalApi`
  - dynamic tool request handling
  - approval request handling
  - tool user-input request handling
- Record the exact request and response payloads needed by the pinned Codex sandbox image.

### Phase 1: runtime capability contract

- Add a new backend module for runtime profiles and capabilities.
- Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/factory/agent.py` to resolve runtime profiles centrally.
- Surface capabilities through session bootstrap or a new realtime/session payload.

### Phase 2: workflow orchestration extraction

- Create a workflow service that centralizes plan/build/continue intent handling.
- Refactor `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/query.py`
  `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/plan.py`
  and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/realtime/handlers/continue_run.py`
  to use the shared workflow layer.
- Introduce canonical plan persistence so `MilestoneTool` becomes a submission mechanism, not the persistence owner.

### Phase 3: Codex workflow bridge

- Refactor `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/src/ii_agent/agents/codex_runtime.py` into a runtime adapter with:
  - experimental API opt-in
  - dynamic tool registration
  - tool-call execution bridge
  - pause request capture
  - resume request resolution
- Preserve existing thread persistence and event streaming behavior.

### Phase 4: frontend capability adoption

- Update `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/hooks/use-question-handlers.tsx`
  and `/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/frontend/src/components/question-input.tsx`
  so workflow availability comes from capabilities instead of `runtime_product`.
- Ensure first-turn website build routing uses workflow intent plus capabilities.

### Phase 5: hardening and rollout

- Add regression coverage for:
  - first-turn Codex website build -> plan generation
  - Codex milestone build execution
  - Codex approval pause -> continue_run
  - non-Codex regression coverage for the same flows
- Remove the Codex-specific plan and continue hard rejections once parity is proven.

## Validation and Acceptance

Behavioral acceptance criteria:

- A Codex-backed `WEBSITE_BUILD` session can generate a persisted project plan and the UI enters the Plan step.
- A Codex-backed session can build one milestone or all milestones and milestone statuses update through the existing plan event path.
- A Codex-backed session can pause for approval or user input and successfully resume through `continue_run`.
- Non-Codex sessions continue to use the same workflow with no regression in plan generation, milestone execution, or pause/resume.
- No frontend workflow gating depends directly on `runtime_product === "codex"`.
- No backend workflow handler rejects Codex by name for plan or continue flow.

Suggested validation commands after implementation:

- `npm --prefix frontend run build`
- `uv run pytest src/tests/unit/engine/test_codex_runtime_agent.py`
- `uv run pytest src/tests/unit/realtime -k "plan or continue or codex"`
- `uv run pytest`

Expected results:

- All targeted tests pass.
- Frontend build succeeds.
- Manual session test confirms Codex and non-Codex sessions follow the same Plan -> Build -> Result user journey.

## Idempotence and Recovery

- Capability-contract work is additive first; it can ship behind a backend feature flag without immediately enabling Codex plan mode in the UI.
- Dynamic tool bridging must be feature-flagged so the repo can fall back to the current Codex transport if protocol assumptions fail in production.
- Remove hard rejections in `plan.py` and `continue_run.py` only after the Codex bridge tests are green.
- If resume bridging proves unstable, keep the new capability contract and plan persistence refactor, but leave Codex `supports_pause_resume = false` until the pending-request storage is correct.

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
