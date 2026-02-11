# workers/celery_worker.py

import logging
from celery import Celery
from orchestration.finance_graph import finance_agent_app
from core.config import settings

logger = logging.getLogger("DeepRouter.Worker")

# ──────────────────────────────────────────────────────────────
# 1. Celery app
# ──────────────────────────────────────────────────────────────
celery_app = Celery(
    "deeprouter_tasks",
    broker=settings.REDIS_URL,
    backend=settings.CELERY_BACKEND_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Reliability: acknowledge task only after the worker finishes,
    # so a worker crash re-queues the task automatically.
    task_acks_late=True,
    # One heavy agent task per worker process — prevents memory pressure
    # from concurrent LangGraph executions.
    worker_prefetch_multiplier=1,
    # Keep results for 24 h so the polling endpoint stays responsive
    result_expires=86400,
)


# ──────────────────────────────────────────────────────────────
# 2. Task definition
# ──────────────────────────────────────────────────────────────
@celery_app.task(bind=True, name="run_quant_agent_task")
def execute_financial_agent(self, ticker: str, user_query: str):
    """
    Bridge between Celery (sync) and LangGraph (sync nodes, async-ready).

    Retry strategy — exponential backoff with jitter cap:
      Attempt 1 (retry 0): 30 s
      Attempt 2 (retry 1): 60 s
      Attempt 3 (retry 2): 120 s   ← max 3 retries, hard-capped at 300 s
    """
    logger.info("Task picked up.", extra={"task_id": self.request.id, "ticker": ticker})

    initial_state = {
        "ticker": ticker,
        "user_query": user_query,
        "market_data": {},
        "options_analysis": {},
        "risk_score": 0.0,
        "recalculate_attempts": 0,
        "messages": [],
    }

    try:
        final_state = finance_agent_app.invoke(initial_state)
        logger.info("Task completed.", extra={"task_id": self.request.id, "ticker": ticker})

        md       = final_state.get("market_data", {})
        analysis = final_state["options_analysis"]

        # Stamp expiry from market_data so the dashboard can display it
        if "options_expiry" in md and analysis:
            analysis["expiry"] = md["options_expiry"]

        return {
            "status":        "success",
            "ticker":        final_state["ticker"],
            "current_price": md.get("current_price"),
            "trend":         md.get("trend"),
            "dte":           md.get("dte"),
            "risk_score":    final_state["risk_score"],
            "analysis":      analysis,
            "logs":          final_state["messages"],
        }

    except Exception as exc:
        # Exponential backoff: 30 s → 60 s → 120 s (capped at 300 s)
        backoff = min(30 * (2 ** self.request.retries), 300)
        logger.warning(
            "Task failed — scheduling retry.",
            extra={
                "task_id": self.request.id,
                "ticker":  ticker,
                "attempt": self.request.retries + 1,
                "backoff": backoff,
                "error":   str(exc),
            },
        )
        raise self.retry(exc=exc, countdown=backoff, max_retries=3)
