# routers/admin.py

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middlewares.auth import register_api_key
from core.config import settings
from core.db_session import db_manager

logger = logging.getLogger("DeepRouter.Admin")

router = APIRouter(prefix="/admin/v1", tags=["Admin"])

# ──────────────────────────────────────────────────────────────
# IP allowlist
# Comma-separated CIDRs or IPs in ADMIN_ALLOWED_IPS env var.
# Default: loopback only.  Set to "0.0.0.0/0" to allow any IP (not recommended).
# In development mode (ENV=development) the check is skipped entirely.
# ──────────────────────────────────────────────────────────────
def _parse_allowed_networks():
    raw = os.getenv("ADMIN_ALLOWED_IPS", "127.0.0.1,::1")
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Invalid ADMIN_ALLOWED_IPS entry — skipped.", extra={"entry": entry})
    return networks

_ALLOWED_NETWORKS = _parse_allowed_networks()


def _is_ip_allowed(client_ip: str) -> bool:
    try:
        addr = ip_address(client_ip)
        return any(addr in net for net in _ALLOWED_NETWORKS)
    except ValueError:
        return False


# ──────────────────────────────────────────────────────────────
# Admin auth dependency
# ──────────────────────────────────────────────────────────────
def _require_admin(request: Request):
    # 1. Secret header check
    secret = request.headers.get("X-Admin-Secret", "")
    if not secret or secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access denied.")

    # 2. IP allowlist (skipped in development for convenience)
    if settings.ENV == "production":
        client_ip = request.client.host if request.client else ""
        if not _is_ip_allowed(client_ip):
            logger.warning(
                "Admin request from disallowed IP blocked.",
                extra={"client_ip": client_ip},
            )
            raise HTTPException(status_code=403, detail="Admin access denied: IP not allowed.")


# ──────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────
class CreateKeyRequest(BaseModel):
    user_id: str
    label: str = ""
    ttl_days: Optional[int] = None  # None = no expiry


class CreateKeyResponse(BaseModel):
    api_key: str          # Raw key — shown exactly once, never stored
    key_hash: str         # SHA-256 fingerprint for revocation
    user_id: str
    label: str
    expires_at: Optional[str]


class KeyRecord(BaseModel):
    key_hash: str
    user_id: str
    label: str
    created_at: str
    expires_at: Optional[str]
    revoked: bool


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────
@router.post("/keys", response_model=CreateKeyResponse, dependencies=[Depends(_require_admin)])
async def create_api_key(body: CreateKeyRequest):
    """
    Generate a new API key for a user.
    The raw key is returned exactly once — only its SHA-256 hash is persisted.
    """
    raw_key  = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at   = None
    ttl_seconds  = 0
    if body.ttl_days:
        expires_at  = datetime.now(timezone.utc) + timedelta(days=body.ttl_days)
        ttl_seconds = body.ttl_days * 86400

    await _store_key_in_db(key_hash=key_hash, user_id=body.user_id,
                           label=body.label, expires_at=expires_at)
    await register_api_key(user_id=body.user_id, raw_key=raw_key,
                           ttl_seconds=ttl_seconds)

    logger.info("API key created.",
                extra={"user_id": body.user_id, "label": body.label,
                       "key_hash_prefix": key_hash[:12]})
    return CreateKeyResponse(
        api_key=raw_key, key_hash=key_hash,
        user_id=body.user_id, label=body.label,
        expires_at=expires_at.isoformat() if expires_at else None,
    )


@router.get("/keys/{user_id}", response_model=list[KeyRecord], dependencies=[Depends(_require_admin)])
async def list_keys(user_id: str):
    """List all API keys (active and revoked) for a given user."""
    pool = db_manager.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key_hash, user_id, label, created_at, expires_at, revoked
            FROM   api_keys
            WHERE  user_id = $1
            ORDER  BY created_at DESC
            """,
            user_id,
        )
    return [
        KeyRecord(
            key_hash=r["key_hash"], user_id=r["user_id"], label=r["label"] or "",
            created_at=r["created_at"].isoformat(),
            expires_at=r["expires_at"].isoformat() if r["expires_at"] else None,
            revoked=r["revoked"],
        )
        for r in rows
    ]


@router.delete("/keys/{key_hash}", dependencies=[Depends(_require_admin)])
async def revoke_api_key(key_hash: str):
    """
    Revoke an API key by its SHA-256 hash.
    Marks it revoked in Postgres and removes it from the Redis cache immediately.
    """
    pool = db_manager.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET revoked = true WHERE key_hash = $1 AND revoked = false",
            key_hash,
        )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Key not found or already revoked.")

    # Remove from Redis cache — next request is immediately rejected
    from core.redis_pool import redis_manager
    try:
        await redis_manager.redis.delete(f"apikey:{key_hash}")
    except Exception:
        pass  # Non-fatal; Postgres is authoritative

    logger.info("API key revoked.", extra={"key_hash_prefix": key_hash[:12]})
    return {"status": "revoked", "key_hash": key_hash}


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────
async def _store_key_in_db(key_hash: str, user_id: str,
                           label: str, expires_at: Optional[datetime]):
    pool = db_manager.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable.")
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO api_keys (key_hash, user_id, label, expires_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (key_hash) DO NOTHING
                """,
                key_hash, user_id, label, expires_at,
            )
    except asyncpg.PostgresError as e:
        logger.error("DB error storing API key.", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to persist API key.")
