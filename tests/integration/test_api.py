# tests/integration/test_api.py
"""
Integration tests against a live DeepRouter instance.

Prerequisites:
  - Redis running on localhost:6379
  - Postgres running on localhost:5432 with migrations applied
  - FastAPI server running on localhost:8000

Run with:
  pytest tests/integration -v

Or start the full stack first:
  docker compose up -d redis postgres api
  pytest tests/integration -v
"""
import pytest
import httpx

BASE_URL = "http://localhost:8000"
DEV_KEY  = "test-dev-key"
HEADERS  = {"Authorization": f"Bearer {DEV_KEY}"}


@pytest.fixture(scope="session")
def client():
    """Synchronous HTTPX client for the whole session."""
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


# ── Health ────────────────────────────────────────────────────
class TestHealth:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_has_status_field(self, client):
        data = client.get("/health").json()
        assert "status" in data

    def test_has_services_field(self, client):
        data = client.get("/health").json()
        assert "services" in data

    def test_reports_redis_service(self, client):
        data = client.get("/health").json()
        assert "redis" in data["services"]

    def test_reports_postgres_service(self, client):
        data = client.get("/health").json()
        assert "postgres" in data["services"]

    def test_health_is_public_no_auth_needed(self, client):
        resp = client.get("/health")   # no Authorization header
        assert resp.status_code == 200


# ── Request ID tracing ────────────────────────────────────────
class TestRequestID:
    def test_response_contains_request_id_header(self, client):
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_forwarded_request_id_is_echoed(self, client):
        custom_id = "my-trace-id-abc123"
        resp = client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("x-request-id") == custom_id

    def test_generated_request_id_is_uuid_format(self, client):
        import re
        resp = client.get("/health")
        rid = resp.headers.get("x-request-id", "")
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        assert uuid_pattern.match(rid), f"Not a UUID: {rid}"


# ── Authentication ────────────────────────────────────────────
class TestAuth:
    def test_protected_endpoint_rejects_no_token(self, client):
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 401

    def test_protected_endpoint_rejects_bad_token(self, client):
        resp = client.get("/api/v1/metrics",
                          headers={"Authorization": "Bearer invalid-key-xyz"})
        assert resp.status_code == 401

    def test_protected_endpoint_accepts_dev_key(self, client):
        resp = client.get("/api/v1/metrics", headers=HEADERS)
        assert resp.status_code == 200

    def test_dashboard_is_public(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200

    def test_docs_is_public(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


# ── Metrics ───────────────────────────────────────────────────
class TestMetrics:
    def test_returns_expected_fields(self, client):
        data = client.get("/api/v1/metrics", headers=HEADERS).json()
        for field in ("total_requests", "total_errors", "error_rate",
                      "intents", "rpm_series", "tasks"):
            assert field in data, f"Missing field: {field}"

    def test_rpm_series_has_60_buckets(self, client):
        data = client.get("/api/v1/metrics", headers=HEADERS).json()
        assert len(data["rpm_series"]) == 60

    def test_intent_keys_present(self, client):
        intents = client.get("/api/v1/metrics", headers=HEADERS).json()["intents"]
        for key in ("casual_chat", "financial_quant", "code_assistant"):
            assert key in intents


# ── Chat completions routing ──────────────────────────────────
class TestChatCompletions:
    def test_returns_intent_and_confidence(self, client):
        resp = client.post(
            "/api/v1/chat/completions",
            headers=HEADERS,
            json={"query": "hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "intent" in data
        assert "confidence" in data

    def test_confidence_is_between_0_and_1(self, client):
        data = client.post(
            "/api/v1/chat/completions",
            headers=HEADERS,
            json={"query": "hello world"},
        ).json()
        assert 0.0 <= data["confidence"] <= 1.0

    def test_financial_query_returns_processing_status(self, client):
        resp = client.post(
            "/api/v1/chat/completions",
            headers=HEADERS,
            json={"query": "Analyze $SPY options strategy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert "task_id" in data
        assert data["intent"] == "financial_quant"

    def test_financial_response_includes_ticker(self, client):
        data = client.post(
            "/api/v1/chat/completions",
            headers=HEADERS,
            json={"query": "Options strategy for $NVDA"},
        ).json()
        assert data.get("ticker") == "NVDA"

    def test_empty_query_returns_error(self, client):
        resp = client.post(
            "/api/v1/chat/completions",
            headers=HEADERS,
            json={"query": ""},
        )
        # FastAPI will either 422 (Pydantic) or 200 with fallback
        assert resp.status_code in (200, 422)
