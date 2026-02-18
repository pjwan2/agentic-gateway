# api/middlewares/metrics.py

import json
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

from core.redis_pool import redis_manager

logger = logging.getLogger("DeepRouter.Metrics")

_RECENT_KEY   = "metrics:recent"
_RECENT_MAX   = 50
_RPM_TTL      = 7200   # 2 hours — enough for a 24-h chart with minute buckets


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Fire-and-forget request metrics recorder.
    Writes to Redis asynchronously; never blocks the response path.

    Tracked keys:
      metrics:total_requests        — total handled requests
      metrics:total_errors          — 4xx / 5xx responses
      metrics:rpm:{unix_minute}     — requests-per-minute buckets (for chart)
      metrics:recent                — list of last 50 request summaries (JSON)
    """

    _SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/dashboard"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._SKIP_PATHS or request.url.path.startswith("/static"):
            return await call_next(request)

        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = round((time.monotonic() - t0) * 1000)

        try:
            await self._record(request, response.status_code, latency_ms)
        except Exception as e:
            logger.debug(f"Metrics write failed (non-fatal): {e}")

        return response

    async def _record(self, request: Request, status_code: int, latency_ms: int):
        redis = redis_manager.redis
        pipe = redis.pipeline()

        pipe.incr("metrics:total_requests")
        if status_code >= 400:
            pipe.incr("metrics:total_errors")

        # Per-minute bucket for sparkline chart
        minute_key = f"metrics:rpm:{int(time.time()) // 60}"
        pipe.incr(minute_key)
        pipe.expire(minute_key, _RPM_TTL)

        # Recent activity log (newest first, capped)
        user_id = getattr(request.state, "user_id", "anonymous")
        entry = json.dumps({
            "ts": int(time.time()),
            "user": user_id,
            "method": request.method,
            "path": request.url.path,
            "status": status_code,
            "ms": latency_ms,
            "intent": getattr(request.state, "intent", None),
        })
        pipe.lpush(_RECENT_KEY, entry)
        pipe.ltrim(_RECENT_KEY, 0, _RECENT_MAX - 1)

        await pipe.execute()


async def record_intent(request: Request, intent: str):
    """
    Called from the route handler after classification.
    Increments per-intent counter and stamps the intent on request.state
    so the recent-activity log can pick it up.
    """
    request.state.intent = intent
    try:
        await redis_manager.redis.incr(f"metrics:intent:{intent}")
    except Exception:
        pass
