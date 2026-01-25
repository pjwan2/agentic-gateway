# api/middlewares/auth.py
"""
Bearer API-key authentication middleware.

Key resolution order (fast → authoritative):
  1. Redis cache  — sub-millisecond; populated by admin key-creation endpoint.
  2. Postgres     — fallback when Redis misses (eviction, restart, first use).
                    Also enforces revoked=false and expires_at checks.
  3. Dev key      — development-only fallback; never valid when ENV=production.

On success, request.state.user_id is set with the trusted identity.
Downstream code must read from request.state, never from spoofable headers.
"""

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import Request
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.config import settings
from core.redis_pool import redis_manager

logger = logging.getLogger("DeepRouter.Auth")

# Paths that bypass authentication entirely
_PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc", "/health", "/dashboard"}

# Redis key namespace: apikey:<sha256(raw_key)> → user_id
_KEY_PREFIX = "apikey:"

# How long to cache a Postgres-validated key in Redis (seconds)
# Short enough to pick up revocations within 5 minutes
_REDIS_REHYDRATE_TTL = 300


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer API keys on every protected request."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or malformed Authorization header. Expected: Bearer <api_key>"},
            )

        raw_key = auth_header.removeprefix("Bearer ").strip()
        user_id = await self._resolve_user(raw_key)

        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired API key."},
            )

        request.state.user_id = user_id
        return await call_next(request)

    # ──────────────────────────────────────────────────────────
    # Resolution chain
    # ──────────────────────────────────────────────────────────
    async def _resolve_user(self, raw_key: str) -> str | None:
        hashed = _hash_key(raw_key)

        # 1. Redis fast path
        user_id = await self._check_redis(hashed)
        if user_id:
            return user_id

        # 2. Postgres authoritative check (handles Redis eviction / restarts,
        #    and enforces revoked + expires_at constraints)
        user_id = await self._check_postgres(hashed)
        if user_id:
            # Re-warm Redis with a short TTL so the next N requests stay fast
            await self._rehydrate_redis(hashed, user_id)
            return user_id

        # 3. Dev-only fallback key
        if settings.DEV_API_KEY and raw_key == settings.DEV_API_KEY:
            if settings.ENV == "production":
                logger.warning("Dev API key presented in production — rejecting.")
                return None
            return "dev-user"

        return None

    async def _check_redis(self, key_hash: str) -> str | None:
        try:
            value = await redis_manager.redis.get(f"{_KEY_PREFIX}{key_hash}")
            return value or None
        except RedisError as e:
            logger.warning("Redis unavailable during auth — falling back to Postgres.", extra={"err": str(e)})
            return None

    async def _check_postgres(self, key_hash: str) -> str | None:
        """
        Look up the key in Postgres.
        Rejects keys that are revoked or past their expires_at timestamp.
        """
        from core.db_session import db_manager

        if not db_manager.pool:
            return None
        try:
            async with db_manager.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT user_id
                    FROM   api_keys
                    WHERE  key_hash  = $1
                      AND  revoked   = false
                      AND  (expires_at IS NULL OR expires_at > now())
                    """,
                    key_hash,
                )
            return row["user_id"] if row else None
        except Exception as e:
            logger.error("Postgres auth check failed.", extra={"err": str(e)})
            return None

    async def _rehydrate_redis(self, key_hash: str, user_id: str) -> None:
        """Write a short-lived cache entry so subsequent requests hit Redis."""
        try:
            await redis_manager.redis.setex(
                f"{_KEY_PREFIX}{key_hash}",
                _REDIS_REHYDRATE_TTL,
                user_id,
            )
        except RedisError:
            pass  # Non-fatal — next request will re-check Postgres


# ──────────────────────────────────────────────────────────────
# Admin helper (used by routers/admin.py)
# ──────────────────────────────────────────────────────────────
async def register_api_key(user_id: str, raw_key: str, ttl_seconds: int = 0) -> None:
    """
    Store a new API key in Redis.
    ttl_seconds=0 → no expiry (permanent until revoked).
    """
    hashed = _hash_key(raw_key)
    redis_key = f"{_KEY_PREFIX}{hashed}"
    if ttl_seconds > 0:
        await redis_manager.redis.setex(redis_key, ttl_seconds, user_id)
    else:
        await redis_manager.redis.set(redis_key, user_id)
