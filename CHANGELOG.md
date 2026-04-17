# Changelog

All notable changes to DeepRouter are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/); versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-04-17

### Added
- Structured JSON logging with Python `contextvars` for async-safe request correlation
- `X-Request-ID` end-to-end tracing — generated or propagated from client, echoed in response
- `RequestIDMiddleware` as the outermost middleware layer
- Production Dockerfile: multi-stage build, non-root `appuser`, baked embedding model layer, HEALTHCHECK
- Full `docker-compose.yml`: redis · postgres · api · celery_worker · nginx — all with healthchecks and `depends_on` conditions
- GitHub Actions CI pipeline: lint → unit tests → integration tests → docker build
- Community health files: CHANGELOG, CONTRIBUTING, SECURITY, issue templates, PR template

### Changed
- `AuthMiddleware` now performs Postgres fallback with `revoked` + `expires_at` enforcement and Redis rehydration (300 s TTL)
- `RateLimitMiddleware` uses `request.state.user_id` (set by auth) instead of a spoofable header
- `main.py` memory injection limited to sync LLM path only (not `financial_quant`)
- README updated with accurate repository URLs and architecture decisions

### Fixed
- Placeholder `your-org` references in README replaced with `pjwan2`

---

## [0.2.0] — 2026-03-14

### Added
- Nginx reverse proxy with TLS 1.2/1.3 termination, HTTP → HTTPS redirect, security headers
- `pytest` test suite: 57 tests across unit and integration suites
- `--fast` flag and `@slow` marker to skip ML model loading in CI unit tests
- Integration test fixtures with live Redis + Postgres using `httpx.AsyncClient`
- Celery exponential backoff retry: 30 s → 60 s → 120 s (max 3 retries)
- `reports/` directory with `.gitkeep` for CI artifact uploads
- `docker-compose.yml` initial version (redis + postgres + api + celery_worker)

### Changed
- `workers/celery_worker.py` retry logic rewritten to use `min(30 * 2**n, 300)` formula
- `Dockerfile` now multi-stage with `gcc` only in builder layer

---

## [0.1.0] — 2026-02-03

### Added
- Project scaffold: `main.py`, `core/config.py`, `core/redis_pool.py`, `core/db_session.py`
- Semantic intent router using `BAAI/bge-small-en-v1.5` — local model, cosine similarity, returns `(intent, confidence)` tuple
- Bearer API key authentication: SHA-256 hashed keys, Redis fast path
- Token bucket rate limiter via atomic Redis Lua script, per-user buckets
- PostgreSQL schema: `user_memories` (pgvector 384-dim) + `api_keys` tables
- Admin API: key provisioning, revocation, IP allowlist (CIDR), `X-Admin-Secret` header
- Celery async task queue for `financial_quant` path
- LangGraph `StateGraph` for quant analysis: `fetch_market_data → quant_analyzer → risk_assessor` with recalculation loop (max 3 attempts)
- `MetricsMiddleware`: RPM buckets, intent counters, recent activity log in Redis
- `HermesMemoryInjector`: per-user `profile_summary` injected into LLM prompt via pgvector
- Real-time dashboard (`dashboard/index.html`): DeepRouter Console, health status, intent donut chart, RPM sparkline, activity table
- `.env.example`, `.gitignore`, `requirements.txt`

[1.0.0]: https://github.com/pjwan2/agentic-gateway/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/pjwan2/agentic-gateway/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pjwan2/agentic-gateway/releases/tag/v0.1.0
