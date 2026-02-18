# routers/metrics.py

import json
import time
import logging
from fastapi import APIRouter

from core.redis_pool import redis_manager
from core.db_session import db_manager

logger = logging.getLogger("DeepRouter.Metrics")

router = APIRouter(tags=["Observability"])

_INTENTS = ["casual_chat", "financial_quant", "code_assistant"]


@router.get("/health")
async def health():
    """
    Deep health check: pings Redis and Postgres.
    Returns per-service status so the dashboard can show individual indicators.
    """
    redis_ok = False
    postgres_ok = False

    try:
        await redis_manager.redis.ping()
        redis_ok = True
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")

    try:
        if db_manager.pool:
            async with db_manager.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            postgres_ok = True
    except Exception as e:
        logger.warning(f"Postgres health check failed: {e}")

    overall = "ok" if (redis_ok and postgres_ok) else "degraded"
    return {
        "status": overall,
        "services": {
            "redis":    "ok" if redis_ok    else "unavailable",
            "postgres": "ok" if postgres_ok else "unavailable",
        },
    }


@router.get("/api/v1/metrics")
async def get_metrics():
    """
    Aggregated gateway metrics for the dashboard.
    All data is read from Redis — sub-millisecond response.
    """
    redis = redis_manager.redis

    # --- Counters (single pipeline round-trip) ---
    pipe = redis.pipeline()
    pipe.get("metrics:total_requests")
    pipe.get("metrics:total_errors")
    for intent in _INTENTS:
        pipe.get(f"metrics:intent:{intent}")
    results = await pipe.execute()

    total_requests = int(results[0] or 0)
    total_errors   = int(results[1] or 0)
    intent_counts  = {
        intent: int(results[2 + i] or 0)
        for i, intent in enumerate(_INTENTS)
    }

    # --- Requests-per-minute sparkline (last 60 minutes) ---
    now_minute = int(time.time()) // 60
    rpm_keys   = [f"metrics:rpm:{now_minute - i}" for i in range(60)]
    rpm_values = await redis.mget(*rpm_keys)
    rpm_series = [int(v or 0) for v in reversed(rpm_values)]  # oldest → newest

    # --- Recent activity ---
    raw_entries = await redis.lrange("metrics:recent", 0, 19)
    recent = []
    for raw in raw_entries:
        try:
            recent.append(json.loads(raw))
        except Exception:
            pass

    # --- Celery task counters ---
    pipe2 = redis.pipeline()
    pipe2.get("metrics:tasks:dispatched")
    pipe2.get("metrics:tasks:completed")
    pipe2.get("metrics:tasks:failed")
    t_results = await pipe2.execute()

    tasks = {
        "dispatched": int(t_results[0] or 0),
        "completed":  int(t_results[1] or 0),
        "failed":     int(t_results[2] or 0),
    }

    return {
        "total_requests": total_requests,
        "total_errors":   total_errors,
        "error_rate":     round(total_errors / total_requests, 4) if total_requests else 0.0,
        "intents":        intent_counts,
        "rpm_series":     rpm_series,
        "tasks":          tasks,
        "recent":         recent,
    }
