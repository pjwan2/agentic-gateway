# api/middlewares/request_id.py
"""
Assigns a unique X-Request-ID to every request and echoes it in the response.

Key behaviours:
  • If the upstream caller (Nginx, API gateway, mobile client) already sends an
    X-Request-ID header, that value is preserved and propagated — enabling
    end-to-end tracing across multiple services.
  • If no header is present a new UUID4 is generated.
  • The ID is injected into request.state so downstream handlers (route
    functions, workers) can log it without touching the raw headers.
  • The ID is also pushed into the async context via core.logging.set_request_context
    so every logger within this request automatically includes it in JSON output.
"""

import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging import set_request_context


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Honour a forwarded ID (from Nginx $request_id or an API client)
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Push into async context — all loggers in this request tree see it
        # user_id not yet available here (AuthMiddleware hasn't run); it will
        # be refreshed by metrics middleware once auth completes.
        set_request_context(request_id=request_id)

        response = await call_next(request)

        # Always echo the ID back so clients can correlate their own logs
        response.headers["X-Request-ID"] = request_id
        return response
