# api/middlewares/rate_limiter.py

import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from redis.exceptions import RedisError
from core.redis_pool import redis_manager

logger = logging.getLogger("DeepRouter.RateLimiter")

# ==========================================
# The "Brain" of the Rate Limiter: Lua Script
# Executed atomically inside Redis to prevent race conditions.
# ==========================================
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate_per_sec = tonumber(ARGV[2])
local requested_tokens = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "last_update")
local current_tokens = tonumber(bucket[1])
local last_update = tonumber(bucket[2])

if not current_tokens then
    current_tokens = max_tokens
    last_update = now
else
    local delta_time = math.max(0, now - last_update)
    local added_tokens = delta_time * refill_rate_per_sec
    current_tokens = math.min(max_tokens, current_tokens + added_tokens)
end

if current_tokens >= requested_tokens then
    current_tokens = current_tokens - requested_tokens
    redis.call("HMSET", key, "tokens", current_tokens, "last_update", now)
    -- Set expiry to avoid cluttering Redis with inactive users
    redis.call("EXPIRE", key, math.ceil(max_tokens / refill_rate_per_sec) * 2)
    return 1 -- Allowed
else
    return 0 -- Rate Limited
end
"""

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Enterprise API Gateway middleware to control LLM cost based on Token usage.
    """
    def __init__(self, app, max_tpm: int = 6000):
        super().__init__(app)
        self.max_tokens = max_tpm          
        self.refill_rate = max_tpm / 60.0  

    async def dispatch(self, request: Request, call_next):
        # 1. Identify the user via the trusted state set by AuthMiddleware.
        # Never read X-User-ID header directly — it is spoofable by any client.
        user_id = getattr(request.state, "user_id", "anonymous")
        redis_key = f"rate_limit:tpm:{user_id}"

        # 2. Estimate token cost for this specific request
        if request.method == "GET":
            requested_tokens = 10
        else:
            # Simple heuristic: 1 byte of payload ~ 0.25 tokens
            body_bytes = await request.body()
            requested_tokens = max(50, len(body_bytes) // 4) 

        # 3. Execute atomic rate limit check via Redis Lua
        try:
            redis_client = redis_manager.redis
            now = int(time.time())

            is_allowed = await redis_client.eval(
                TOKEN_BUCKET_LUA,
                1,
                redis_key,
                self.max_tokens,
                self.refill_rate,
                requested_tokens,
                now
            )

            # 4. Block if bucket is empty
            if not is_allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests: Token usage exceeded your tier limit."}
                )

        except RedisError as e:
            # Intentional fail-open: if Redis is unavailable the rate limiter
            # bypasses enforcement rather than blocking all traffic.
            #
            # Tradeoff rationale: the gateway serves as a routing layer in front
            # of downstream LLMs that have their own provider-side rate limits.
            # A Redis outage is already an incident; adding a hard 503 on every
            # request would compound the blast radius unnecessarily.
            #
            # Mitigation: alert on Redis health-check failure (see /health) and
            # restore Redis before sustained abuse can accumulate.
            logger.warning(
                "Rate limiter bypassed — Redis unavailable.",
                extra={"error": str(e), "user_id": user_id},
            )

        # 5. Pass to the next layer (Semantic Router, etc.)
        return await call_next(request)