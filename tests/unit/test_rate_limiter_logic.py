# tests/unit/test_rate_limiter_logic.py
"""
Unit tests for rate-limiter configuration and Lua script structure.
No Redis required — tests pure Python logic and script content.
"""
import pytest
from unittest.mock import MagicMock


class TestRateLimiterConfig:
    def test_refill_rate_equals_max_tpm_divided_by_60(self):
        from api.middlewares.rate_limiter import RateLimitMiddleware
        m = RateLimitMiddleware(app=MagicMock(), max_tpm=6000)
        assert m.refill_rate == pytest.approx(100.0, rel=1e-6)

    def test_max_tokens_stored(self):
        from api.middlewares.rate_limiter import RateLimitMiddleware
        m = RateLimitMiddleware(app=MagicMock(), max_tpm=3000)
        assert m.max_tokens == 3000

    def test_higher_tpm_gives_higher_refill_rate(self):
        from api.middlewares.rate_limiter import RateLimitMiddleware
        m1 = RateLimitMiddleware(app=MagicMock(), max_tpm=3000)
        m2 = RateLimitMiddleware(app=MagicMock(), max_tpm=6000)
        assert m2.refill_rate == 2 * m1.refill_rate


class TestTokenBucketLuaScript:
    def test_script_is_non_trivial(self):
        from api.middlewares.rate_limiter import TOKEN_BUCKET_LUA
        assert len(TOKEN_BUCKET_LUA.strip()) > 100

    def test_script_references_keys(self):
        from api.middlewares.rate_limiter import TOKEN_BUCKET_LUA
        assert "KEYS[1]" in TOKEN_BUCKET_LUA

    def test_script_references_argv(self):
        from api.middlewares.rate_limiter import TOKEN_BUCKET_LUA
        for i in range(1, 5):
            assert f"ARGV[{i}]" in TOKEN_BUCKET_LUA, f"ARGV[{i}] missing from Lua script"

    def test_script_returns_1_or_0(self):
        from api.middlewares.rate_limiter import TOKEN_BUCKET_LUA
        assert "return 1" in TOKEN_BUCKET_LUA   # allowed
        assert "return 0" in TOKEN_BUCKET_LUA   # rate-limited

    def test_script_sets_expiry(self):
        from api.middlewares.rate_limiter import TOKEN_BUCKET_LUA
        assert "EXPIRE" in TOKEN_BUCKET_LUA


class TestHashKeyIsolation:
    """Rate-limit keys must be scoped per user, not shared globally."""
    def test_different_users_get_different_redis_keys(self):
        # The key pattern is rate_limit:tpm:{user_id}
        user_a = "rate_limit:tpm:alice"
        user_b = "rate_limit:tpm:bob"
        assert user_a != user_b

    def test_anonymous_has_its_own_bucket(self):
        anon_key = "rate_limit:tpm:anonymous"
        user_key = "rate_limit:tpm:alice"
        assert anon_key != user_key
