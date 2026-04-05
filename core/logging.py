# core/logging.py
"""
Structured JSON logging for DeepRouter.

Every log line is a single JSON object — compatible with ELK, Datadog, Cloud Logging.
request_id and user_id are automatically injected from async context vars so all
log lines within a single request are correlatable without passing the values manually.

Usage:
    from core.logging import configure_logging, set_request_context

    # Once at startup:
    configure_logging(level="INFO", json_logs=True)

    # Per-request (called by RequestIDMiddleware automatically):
    set_request_context(request_id="abc-123", user_id="user-42")
"""

import contextvars
import json
import logging
import time
from typing import Any

# ──────────────────────────────────────────────────────────────
# Async-safe context variables
# ──────────────────────────────────────────────────────────────
# These are set once per request by RequestIDMiddleware and are
# readable from any coroutine running in that request's task tree.
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_user_id_var:    contextvars.ContextVar[str] = contextvars.ContextVar("user_id",    default="")


def set_request_context(request_id: str = "", user_id: str = "") -> None:
    """Inject per-request identifiers into the current async context."""
    _request_id_var.set(request_id)
    _user_id_var.set(user_id)


# ──────────────────────────────────────────────────────────────
# JSON formatter
# ──────────────────────────────────────────────────────────────
_STDLIB_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class _JSONFormatter(logging.Formatter):
    """Serialises every LogRecord to a compact JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts":     self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }

        # Attach request-scoped identifiers when available
        if rid := _request_id_var.get():
            entry["request_id"] = rid
        if uid := _user_id_var.get():
            entry["user_id"] = uid

        # Caller can pass extra={} fields to logging calls
        for key, val in record.__dict__.items():
            if key not in _STDLIB_KEYS:
                try:
                    json.dumps(val)          # keep only JSON-serialisable values
                    entry[key] = val
                except (TypeError, ValueError):
                    entry[key] = str(val)

        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# Public configure function
# ──────────────────────────────────────────────────────────────
def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """
    Call exactly once at application startup (before any logger is used).

    Args:
        level:     Python log level string, e.g. "INFO", "DEBUG", "WARNING".
        json_logs: True  → machine-readable JSON (production / CI).
                   False → human-readable text (local development).
    """
    handler = logging.StreamHandler()

    if json_logs:
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[handler],
        force=True,      # override any handlers set by libraries (e.g. uvicorn)
    )
