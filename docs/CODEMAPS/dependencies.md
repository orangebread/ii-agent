<!-- Generated: 2026-03-29 | External: 12 | Config: 13 | Token estimate: ~600 -->
# Dependencies

## External Services

| Service | Purpose | Config |
|---------|---------|--------|
| PostgreSQL | Primary database | `core/config/database.py::DatabaseSettings` |
| Redis | Cache, pubsub, cancel tokens | `core/config/redis.py::RedisSettings` |
| Google Cloud Storage | File storage (prod) | `core/config/storage.py::StorageSettings` |
| Stripe | Payments, subscriptions | `core/config/stripe.py::StripeSettings` |
| E2B / Daytona | Sandbox execution providers | `core/config/sandbox.py::SandboxSettings` |
| Anthropic | Claude LLM provider | via `anthropic[vertex]` |
| OpenAI | GPT models + embeddings | via `openai` |
| Google GenAI | Gemini models | via `google-genai` |
| Composio | External tool integrations | `integrations/connectors/composio/` |
| Tavily | Web search | via `tavily-python` |
| DuckDuckGo | Web search fallback | via `duckduckgo-search` |
| FastAPI-SSO | OAuth 2.0 (Google, GitHub, MS) | `core/config/oauth.py::OAuth2Settings` |

## Configuration Hierarchy

Main: `core/config/settings.py::Settings` (Pydantic BaseSettings, `@lru_cache` singleton via `get_settings()`)

| Config Class | File | Key Fields |
|-------------|------|------------|
| `DatabaseSettings` | `core/config/database.py` | url, pool_size, timeout |
| `RedisSettings` | `core/config/redis.py` | url, mode |
| `StorageSettings` | `core/config/storage.py` | provider (gcs/local), bucket, domain |
| `SandboxSettings` | `core/config/sandbox.py` | provider (e2b/docker/daytona/local), api_key, template/image/snapshot |
| `StripeSettings` | `core/config/stripe.py` | secret_key, webhook_secret, price_ids |
| `OAuth2Settings` | `core/config/oauth.py` | client_ids, secrets, redirect_uris |
| `LLMConfig` | `core/config/llm_config.py` | model pricing, token limits |
| `CreditsSettings` | `core/config/credits.py` | default allocations |
| `AgentSettings` | `core/config/agent.py` | execution parameters |
| `MCPSettings` | `core/config/mcp.py` | MCP server config |
| `MobileSettings` | `core/config/mobile.py` | mobile app keys |
| `EnhancePromptConfig` | `core/config/enhance_prompt_config.py` | prompt service |
| `NanoBananaConfig` | `core/config/nano_banana.py` | model config |
| `SessionTitleConfig` | `core/config/session_title.py` | title generation |

## Infrastructure Components

### Service Container (`core/container.py::ApplicationContainer`)
Global singleton. Created via `ApplicationContainer.init()` during lifespan.
Access: `ContainerDep` (FastAPI requests) or `get_app_container()` (Socket.IO, cron, workers).
Wires 21+ domain services + repositories at startup.

### PubSub (`realtime/pubsub/asyncio_pubsub.py::AsyncIOPubSub`)
Topic-based async publish/subscribe with two global subscribers:
- `SioCallbackHandler` → Socket.IO room broadcast
- `DatabaseCallbackHandler` → `application_events` persistence

### Storage Providers
- `core/storage/providers/gcs.py` — Google Cloud Storage (production)
- `core/storage/providers/local.py` — Local filesystem (development)
- `core/storage/path_resolver.py` — Deterministic path generation for user/session files

### Redis Modules
- `core/redis/client.py` — Async Redis singleton
- `core/redis/cache.py` — Caching utilities
- `core/redis/cancel.py` — Cancellation token management

## Key Python Packages

```
fastapi, uvicorn, socketio       # Web framework
sqlalchemy[asyncio], alembic     # Database ORM + migrations
pydantic, pydantic-settings      # Validation + config
redis[hiredis]                   # Cache + pubsub
anthropic[vertex]                # Claude API
openai                           # OpenAI API
google-genai                     # Gemini API
stripe                           # Payments
google-cloud-storage             # File storage
e2b-code-interpreter             # Sandbox
celery                           # Task queue
apscheduler                      # Cron scheduling
```
