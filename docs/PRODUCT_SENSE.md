# Product Sense

## What II-Agent Is

II-Agent is an AI agent platform that shifts interaction from passive chat to autonomous task execution. Users describe what they want — a web app, a presentation, a research report — and the agent builds it end-to-end with real code, real deployments, and real files.

Web application: [agent.ii.inc](https://agent.ii.inc/)

## Three Product Pillars

### 1. Full-Stack Development

The agent scaffolds, develops, and deploys complete web applications in isolated sandbox providers such as E2B or self-hosted Daytona. Users iterate conversationally — "add a login page", "change the color scheme", "deploy to production" — while the agent handles code generation, file management, and Cloud Run deployment.

**Key domains:** `agent/`, `projects/`, `files/`, `integrations/connectors/`

### 2. Slide & Storybook Creation

Transform short briefs into polished presentations or visual storybooks. The agent generates HTML slides, applies design templates, handles image generation, and exports to PDF.

**Key domains:** `content/slides/`, `content/storybook/`, `content/media/`

### 3. Deep Research

Integration with II-Researcher for comprehensive research tasks. The agent searches the web, analyzes sources, and produces structured reports — bridgeable to website generation via session forking (`ForkType.RESEARCH_TO_WEBSITE`).

**Key domains:** `sessions/fork_service.py`, `agent/`, `chat/media/`

## Two Interaction Modes

| Mode | `app_kind` | Transport | Billing | Use case |
|------|-----------|-----------|---------|----------|
| **Agent** | `"agent"` | Socket.IO (real-time streaming) | Per-call in agent loop | Multi-step tasks with tools, sandbox, deployments |
| **Chat** | `"chat"` | REST + SSE | Per-call via LLMExecutionService | Single-turn conversations across multiple LLM providers |

## User Personas

### Power User (Daily)
- Uses agent mode for iterative development
- Manages multiple sessions/projects
- Connects API keys for preferred LLM providers
- Uses MCP and custom skills

### Casual User
- Uses chat mode for quick questions across models
- Creates slides and storybooks from briefs
- Shares public sessions

### Developer (API)
- Integrates via API keys (`ii_<32chars>`)
- Uses A2A (Agent-to-Agent) protocol
- Connects MCP SSE server to ChatGPT

## Key User Journeys

### Agent Session
```
Login (OAuth) → Create session → Agent executes (streaming events) →
  View results → Iterate → Deploy project → Share public URL
```

### Chat Session
```
Login → Send message (select model) → Receive streamed response →
  Continue conversation → Switch models mid-thread
```

### Slide Creation
```
Login → Describe slides → Agent generates HTML slides →
  Review → Request edits → Export PDF
```

## Credit System (User Perspective)

- Users receive credits on signup and subscription renewal
- Every LLM call and tool use costs credits (converted from USD)
- Bonus credits consumed first, then regular credits
- Credit balance visible via `/credits` endpoint
- Insufficient credits blocks further work (minimum 128 output tokens must be affordable)

## Supported LLM Providers

Models available in `billing/credits/pricing.py`:

| Provider | Models |
|----------|--------|
| **Anthropic** | Claude Opus 4.6, Opus 4.5, Sonnet 4.5, Haiku 3.5 |
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o1-mini, o3 |
| **Google** | Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.0 Flash |

Users can bring their own API keys via `/user-settings/models`.
