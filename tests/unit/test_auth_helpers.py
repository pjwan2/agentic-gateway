# tests/unit/test_auth_helpers.py
"""
Unit tests for auth helper functions.
All Redis and Postgres calls are mocked — no external services needed.
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── _hash_key ─────────────────────────────────────────────────
class TestHashKey:
    def test_produces_sha256_hex(self):
        from api.middlewares.auth import _hash_key
        raw = "my-test-api-key"
        assert _hash_key(raw) == hashlib.sha256(raw.encode()).hexdigest()

    def test_output_length_is_64(self):
        from api.middlewares.auth import _hash_key
        assert len(_hash_key("anything")) == 64

    def test_is_deterministic(self):
        from api.middlewares.auth import _hash_key
        assert _hash_key("abc") == _hash_key("abc")

    def test_different_inputs_differ(self):
        from api.middlewares.auth import _hash_key
        assert _hash_key("key-A") != _hash_key("key-B")

    def test_empty_string_does_not_raise(self):
        from api.middlewares.auth import _hash_key
        result = _hash_key("")
        assert len(result) == 64


# ── AuthMiddleware._resolve_user ──────────────────────────────
class TestResolveUser:
    @pytest.fixture
    def middleware(self):
        from api.middlewares.auth import AuthMiddleware
        return AuthMiddleware(app=MagicMock())

    @pytest.mark.asyncio
    async def test_redis_hit_returns_user(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm:
            mock_rm.redis.get = AsyncMock(return_value="user-42")
            result = await middleware._resolve_user("valid-key")
        assert result == "user-42"

    @pytest.mark.asyncio
    async def test_redis_miss_falls_back_to_postgres(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm, \
             patch("api.middlewares.auth.db_manager") as mock_dm:
            mock_rm.redis.get  = AsyncMock(return_value=None)
            mock_rm.redis.setex = AsyncMock()

            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value={"user_id": "pg-user"})
            mock_dm.pool = MagicMock()
            mock_dm.pool.acquire = MagicMock(
                return_value=_async_ctx(mock_conn)
            )

            result = await middleware._resolve_user("postgres-key")
        assert result == "pg-user"

    @pytest.mark.asyncio
    async def test_rehydrates_redis_after_postgres_hit(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm, \
             patch("api.middlewares.auth.db_manager") as mock_dm:
            mock_rm.redis.get   = AsyncMock(return_value=None)
            mock_rm.redis.setex = AsyncMock()

            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value={"user_id": "pg-user"})
            mock_dm.pool = MagicMock()
            mock_dm.pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))

            await middleware._resolve_user("postgres-key")
            mock_rm.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_dev_key_resolves_in_development(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm, \
             patch("api.middlewares.auth.db_manager") as mock_dm:
            mock_rm.redis.get = AsyncMock(return_value=None)
            mock_dm.pool = None   # no DB in dev

            result = await middleware._resolve_user("test-dev-key")
        assert result == "dev-user"

    @pytest.mark.asyncio
    async def test_unknown_key_returns_none(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm, \
             patch("api.middlewares.auth.db_manager") as mock_dm:
            mock_rm.redis.get = AsyncMock(return_value=None)
            mock_dm.pool = None

            result = await middleware._resolve_user("totally-unknown-key-xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_revoked_postgres_key_returns_none(self, middleware):
        with patch("api.middlewares.auth.redis_manager") as mock_rm, \
             patch("api.middlewares.auth.db_manager") as mock_dm:
            mock_rm.redis.get = AsyncMock(return_value=None)

            mock_conn = AsyncMock()
            # Postgres returns no row (revoked=true filtered out by query)
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_dm.pool = MagicMock()
            mock_dm.pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))

            result = await middleware._resolve_user("revoked-key")
        assert result is None


# ── Helpers ───────────────────────────────────────────────────
class _async_ctx:
    """Minimal async context manager for mocking pool.acquire()."""
    def __init__(self, obj):
        self._obj = obj
    async def __aenter__(self):
        return self._obj
    async def __aexit__(self, *_):
        pass
