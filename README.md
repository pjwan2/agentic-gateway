# DeepRouter — Agentic Gateway

> **An enterprise-grade intelligent API gateway that semantically routes natural language queries to the right AI backend — LLM, autonomous agent, or async task queue — with memory injection, observability, and production-ready infrastructure.**

[![CI](https://github.com/pjwan2/agentic-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/pjwan2/agentic-gateway/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What Is DeepRouter?

Most AI applications hard-code a single LLM endpoint. DeepRouter is different — it acts as an **intelligent routing layer** that sits between your users and your AI backends.

Every incoming query is:
1. **Classified** by a local embedding model (zero external API calls, sub-millisecond latency)
2. **Personalized** via per-user memory injection (pgvector long-term context)
3. **Dispatched** to the right backend — a fast LLM for chat/code, or an autonomous LangGraph agent for complex async work

The finance quant analyzer included here is one example agent wired into the gateway. The architecture is designed to plug in any number of agents or LLM endpoints.

```
User Query
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Middleware Stack                                            │
│  RequestID → AuthMiddleware → RateLimiter → Metrics → CORS  │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Semantic Router  (BAAI/bge-small-en-v1.5 · local model)    │
│  casual_chat │ financial_quant │ code_assistant              │
└──────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐          ┌────────────────────────────────┐
│  LiteLLM        │          │  Celery + LangGraph            │
│  (sync · fast)  │          │  ├─ fetch_market_data          │
│  gpt-4o-mini    │          │  ├─ quant_analyzer             │
│  gpt-4o         │          │  └─ risk_assessor (loop)       │
└─────────────────┘          └────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  Memory Layer  (HermesMemoryInjector)                        │
│  Postgres pgvector → profile_summary → augments LLM prompt  │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Features

| Layer | Feature |
|-------|---------|
| **Routing** | Local BAAI/bge-small-en-v1.5 embedding model · pre-computed anchors · cosine similarity · confidence score returned |
| **Auth** | SHA-256 hashed API keys · Redis fast path + Postgres authoritative fallback · `expires_at` / `revoked` enforcement · dev key isolation |
| **Rate Limiting** | Token Bucket algorithm · Redis Lua atomic script · per-user buckets · fail-open on Redis outage |
| **Memory** | Per-user `profile_summary` in Postgres · pgvector embedding (384-dim) index for future semantic search |
| **Agents** | LangGraph `StateGraph` with conditional edges · recalculation loop with risk gating · 3-strategy options analysis (Bull Put / Bear Call / Iron Condor) |
| **Async Tasks** | Celery + Redis broker · `task_acks_late` for crash-safe delivery · exponential backoff retry (30 → 60 → 120 s) |
| **Observability** | Structured JSON logs · `X-Request-ID` end-to-end tracing · RPM sparkline · intent distribution · per-minute metrics in Redis |
| **TLS** | Nginx reverse proxy · TLS 1.2/1.3 only · HTTP → HTTPS redirect · HSTS-ready · security headers |
| **Admin API** | Key provisioning / revocation · IP allowlist (CIDR) · admin secret header · SHA-256 hash only ever stored |
| **CI/CD** | GitHub Actions: lint → unit tests → integration tests → Docker build |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| Semantic Router | Sentence-Transformers (`BAAI/bge-small-en-v1.5`) + scikit-learn |
| LLM Routing | LiteLLM (provider-agnostic: OpenAI, Anthropic, local) |
| Agent Orchestration | LangGraph |
| Async Task Queue | Celery + Redis |
| Vector Database | PostgreSQL + pgvector (384-dim embeddings) |
| Cache / Broker | Redis 7 |
| Market Data | yfinance |
| Reverse Proxy / TLS | Nginx 1.25 |
| Containerization | Docker + Docker Compose |
| Testing | pytest · pytest-asyncio · httpx |
| Linting | ruff |

---

## Project Structure

```
agentic-gateway/
├── main.py                        # FastAPI app, middleware wiring, routing logic
├── agents/
│   └── semantic_router.py         # Local embedding model, intent classification
├── api/middlewares/
│   ├── request_id.py              # X-Request-ID end-to-end tracing
│   ├── auth.py                    # Bearer key auth, Redis + Postgres resolution
│   ├── rate_limiter.py            # Token Bucket via Redis Lua script
│   ├── metrics.py                 # RPM buckets, intent counters, activity log
│   └── context_injector.py        # HermesMemoryInjector — pgvector memory
├── orchestration/
│   └── finance_graph.py           # LangGraph: data → quant → risk → loop
├── workers/
│   └── celery_worker.py           # Celery task, exponential backoff retry
├── routers/
│   ├── admin.py                   # Key management + IP allowlist
│   ├── tasks.py                   # Task polling + cancellation
│   └── metrics.py                 # /health + /api/v1/metrics endpoints
├── core/
│   ├── config.py                  # Settings, env-var loading
│   ├── logging.py                 # JSON formatter + contextvars
│   ├── redis_pool.py              # Async Redis connection pool
│   └── db_session.py              # asyncpg connection pool
├── migrations/
│   └── 001_initial_schema.sql     # user_memories (pgvector) + api_keys tables
├── dashboard/
│   └── index.html                 # Real-time monitoring + DeepRouter Console
├── nginx/
│   ├── nginx.conf                 # TLS termination, security headers
│   └── generate_dev_certs.sh      # Self-signed cert generator (dev only)
├── tests/
│   ├── unit/                      # Pure logic tests — no external services
│   └── integration/               # Full-stack tests against live server
├── Dockerfile                     # Multi-stage build, non-root user, baked model
├── docker-compose.yml             # redis · postgres · api · celery · nginx
└── .github/workflows/ci.yml       # lint → unit → integration → docker build
```

---

## Quick Start

### Option A — Docker (recommended)

```bash
# 1. Clone
git clone https://github.com/pjwan2/agentic-gateway.git
cd agentic-gateway

# 2. Configure
cp .env.example .env          # edit API keys as needed

# 3. Generate dev TLS certificates
bash nginx/generate_dev_certs.sh

# 4. Start all services
docker compose up --build

# 5. Open the dashboard
open https://localhost/dashboard
```

Services started:

| Service | Port |
|---------|------|
| Nginx (HTTPS) | 443 |
| Nginx (HTTP → HTTPS redirect) | 80 |
| FastAPI (internal) | 8000 |
| Redis | 6381 |
| Postgres + pgvector | 5434 |

---

### Option B — Local Development

**Prerequisites:** Python 3.12, Redis, PostgreSQL with pgvector

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env

# 3. Apply database migrations
psql $POSTGRES_URL -f migrations/001_initial_schema.sql

# 4. Start FastAPI
uvicorn main:app --reload --port 8003

# 5. Start Celery worker (separate terminal)
celery -A workers.celery_worker worker --pool=solo --loglevel=info

# 6. Open dashboard
open http://localhost:8003/dashboard
```

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and edit:

```env
# Runtime
ENV=development                   # "production" enforces stricter checks

# Infrastructure
REDIS_URL=redis://localhost:6381/0
CELERY_BACKEND_URL=redis://localhost:6381/1
POSTGRES_URL=postgresql://admin:password123@localhost:5434/deeprouter

# LLM
LITELLM_API_KEY=sk-...            # OpenAI / Anthropic / any LiteLLM provider
DEFAULT_FAST_MODEL=gpt-4o-mini
CODE_MODEL=gpt-4o

# Auth
DEV_API_KEY=dev-secret-key        # Only valid when ENV=development
ADMIN_SECRET=your-admin-secret

# Security
ADMIN_ALLOWED_IPS=127.0.0.1,::1  # Comma-separated CIDRs (production only)
MAX_TPM=6000                      # Token-per-minute rate limit per user

# Observability
LOG_LEVEL=INFO
```

---

## API Reference

All endpoints (except `/health`, `/docs`, `/dashboard`) require:
```
Authorization: Bearer <api_key>
```

### Routing

```http
POST /api/v1/chat/completions
Content-Type: application/json

{ "query": "Analyze $NVDA options strategy" }
```

**Response — async (financial_quant):**
```json
{
  "status": "processing",
  "task_id": "abc-123",
  "ticker": "NVDA",
  "intent": "financial_quant",
  "confidence": 0.871,
  "message": "Long-running quantitative analysis initiated."
}
```

**Response — sync (casual_chat / code_assistant):**
```json
{
  "status": "completed",
  "intent": "casual_chat",
  "confidence": 0.763,
  "response": "..."
}
```

### Task Polling

```http
GET  /api/v1/tasks/{task_id}    # Poll for result
DELETE /api/v1/tasks/{task_id}  # Cancel task
```

### Observability

```http
GET /health                     # Redis + Postgres ping (public)
GET /api/v1/metrics             # RPM, intent distribution, error rate
```

### Admin

```http
POST   /admin/v1/keys           # Provision API key  (X-Admin-Secret required)
GET    /admin/v1/keys/{user_id} # List user keys
DELETE /admin/v1/keys/{hash}    # Revoke key
```

---

## Dashboard

The built-in dashboard at `/dashboard` provides:

- **DeepRouter Console** — send any query, see intent detection + confidence score, then the routed result (LLM text or options strategy)
- **System Health** — live Redis, Postgres, Celery, Gateway status
- **Metrics Cards** — total requests, tasks dispatched, error rate
- **Intent Donut Chart** — real-time distribution of `casual_chat / financial_quant / code_assistant`
- **RPM Sparkline** — requests-per-minute over the last 60 minutes
- **Recent Activity Table** — last 20 requests with user, path, intent, status, latency

---

## Running Tests

```bash
# Fast unit tests (no ML model loading, no external services)
pytest tests/unit --fast -v

# Full unit tests including semantic router accuracy
pytest tests/unit -v

# Integration tests (requires running server + Redis + Postgres)
pytest tests/integration -v

# All tests
pytest -v
```

### Test Coverage

| Suite | Tests | Requires |
|-------|-------|---------|
| `test_semantic_router.py` | 12 | ML model (marked `@slow`) |
| `test_auth_helpers.py` | 8 | Mocked Redis + DB |
| `test_rate_limiter_logic.py` | 9 | None |
| `test_ticker_extraction.py` | 8 | None |
| `test_api.py` (integration) | 20 | Live server |

---

## Production Deployment

### 1. TLS Certificates

Replace the self-signed dev certs with real ones:

```bash
# Let's Encrypt (recommended)
certbot certonly --standalone -d yourdomain.com

cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/certs/server.crt
cp /etc/letsencrypt/live/yourdomain.com/privkey.pem   nginx/certs/server.key
```

### 2. Production Environment

Set these in your `.env` or secrets manager:

```env
ENV=production
LITELLM_API_KEY=sk-...              # Real API key
ADMIN_SECRET=<strong-random-secret>
ADMIN_ALLOWED_IPS=10.0.0.0/8       # Internal network only
DEV_API_KEY=                        # Leave empty — disabled in production
LOG_LEVEL=INFO
```

### 3. Provision Your First API Key

```bash
curl -X POST https://yourdomain.com/admin/v1/keys \
  -H "X-Admin-Secret: your-admin-secret" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "label": "prod-frontend", "ttl_days": 90}'

# Response includes api_key (shown once, never stored again)
```

### 4. Scale

```bash
# Scale Celery workers for more concurrent agent tasks
docker compose up --scale celery_worker=4 -d
```

---

## Architecture Decisions

**Why a local embedding model for routing?**
Sending every query to OpenAI just to classify intent adds ~300 ms latency and ~$0.001 per request. The BAAI/bge-small-en-v1.5 model runs locally in ~2 ms after warm-up with no API cost.

**Why Celery for the finance agent?**
LangGraph workflows can take 5-30 seconds (live market data fetch + multiple LLM calls). Handling this synchronously would block FastAPI workers. Celery decouples execution — the client gets a task ID immediately and polls for completion.

**Why Redis as auth cache + broker?**
Two different databases (Redis for speed, Postgres for durability) give the best of both worlds. Auth checks Redis first (~0.5 ms); Postgres is the fallback and source of truth. On Redis restart, keys are re-validated and re-cached transparently.

**Why the risk recalculation loop in LangGraph?**
A risk score > 0.7 means the reward/risk ratio is poor. Rather than returning a bad trade, the agent widens the spread and recalculates — up to 3 times. This demonstrates conditional agent reasoning beyond simple LLM calls.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run tests: `pytest tests/unit --fast -v`
4. Run linter: `ruff check .`
5. Open a pull request against `main`

---

## License

MIT License — see [LICENSE](LICENSE) for details.
