# main.py

from dotenv import load_dotenv
load_dotenv()   # loads .env before any settings are read

import os
import re
import logging
from contextlib import asynccontextmanager

import litellm
from fastapi import FastAPI, APIRouter, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Internal imports ──────────────────────────────────────────
from core.config import settings
from core.logging import configure_logging, set_request_context
from core.redis_pool import redis_manager
from core.db_session import db_manager
from api.middlewares.request_id import RequestIDMiddleware
from api.middlewares.auth import AuthMiddleware
from api.middlewares.rate_limiter import RateLimitMiddleware
from api.middlewares.metrics import MetricsMiddleware, record_intent
from api.middlewares.context_injector import HermesMemoryInjector
from agents.semantic_router import semantic_router
from workers.celery_worker import execute_financial_agent
from routers.admin import router as admin_router
from routers.tasks import router as tasks_router
from routers.metrics import router as metrics_router

# ──────────────────────────────────────────────────────────────
# 1. Logging — must be configured before any logger is created
# ──────────────────────────────────────────────────────────────
_json_logs = os.getenv("ENV", "development") != "development"
configure_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    json_logs=_json_logs,          # JSON in prod/CI, human-readable in local dev
)
logger = logging.getLogger("DeepRouter")

# ──────────────────────────────────────────────────────────────
# 2. LiteLLM global config
# ──────────────────────────────────────────────────────────────
litellm.api_key = settings.LITELLM_API_KEY

# ──────────────────────────────────────────────────────────────
# 3. Dependency injection
# ──────────────────────────────────────────────────────────────
def get_memory_injector():
    return HermesMemoryInjector(db_manager.pool)

# ──────────────────────────────────────────────────────────────
# 4. Lifespan
# ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Initializing DeepRouter Enterprise Gateway...")
    await redis_manager.init_pool()
    await db_manager.init_pool()
    yield
    logger.info("Graceful shutdown initiated.")
    await redis_manager.close()
    await db_manager.close()

# ──────────────────────────────────────────────────────────────
# 5. Application setup
# ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="DeepRouter — Agentic Gateway",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware stack (outermost first):
#   RequestID → Auth → RateLimit → Metrics → CORS
#
# RequestID must be outermost so every log line from every other
# middleware already has the request_id in context.
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
]
app.add_middleware(CORSMiddleware,
                   allow_origins=_allowed_origins,
                   allow_credentials=True,
                   allow_methods=["*"],
                   allow_headers=["*"])
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitMiddleware, max_tpm=int(os.getenv("MAX_TPM", "6000")))
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIDMiddleware)   # outermost — stamps all logs

# ──────────────────────────────────────────────────────────────
# 6. Static files — Dashboard
# ──────────────────────────────────────────────────────────────
_dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard")
app.mount("/static", StaticFiles(directory=_dashboard_dir), name="static")

@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(os.path.join(_dashboard_dir, "index.html"))

# ──────────────────────────────────────────────────────────────
# 7. Core routing logic
# ──────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/v1")

class PromptRequest(BaseModel):
    query: str

@router.post("/chat/completions", tags=["Agentic Core"])
async def route_traffic(
    request: PromptRequest,
    http_request: Request,
    injector: HermesMemoryInjector = Depends(get_memory_injector),
):
    """
    Main entry point.
    1. Classify intent via local embedding model (zero external API calls).
    2. For financial_quant → dispatch Celery/LangGraph task (async).
    3. For casual_chat / code_assistant → inject memory, call LiteLLM (sync).
    """
    user_id   = getattr(http_request.state, "user_id", "anonymous")
    request_id = getattr(http_request.state, "request_id", "")
    raw_query = request.query

    # Refresh log context with the now-known user_id
    set_request_context(request_id=request_id, user_id=user_id)
    logger.info("Query received.", extra={"intent_phase": "routing"})

    # Phase 1: Semantic routing (local model, sub-millisecond)
    intent, confidence = semantic_router.classify_intent(raw_query)
    logger.info("Intent classified.",
                extra={"intent": intent, "confidence": confidence})

    # Record intent counter for dashboard metrics (fire-and-forget)
    await record_intent(http_request, intent)

    # Phase 2: Dispatch
    if intent == "financial_quant":
        # Memory injection is LLM-specific — the LangGraph nodes use live
        # market data and don't benefit from user profile context.
        ticker = _extract_ticker(raw_query)
        celery_task = execute_financial_agent.delay(
            ticker=ticker, user_query=raw_query
        )
        try:
            await redis_manager.redis.incr("metrics:tasks:dispatched")
        except Exception:
            pass
        logger.info("Quant task dispatched.",
                    extra={"task_id": celery_task.id, "ticker": ticker})
        return {
            "status":     "processing",
            "task_id":    celery_task.id,
            "ticker":     ticker,
            "intent":     intent,
            "confidence": confidence,
            "message":    "Long-running quantitative analysis initiated.",
        }

    # Sync path: inject memory then call LiteLLM
    augmented_query = await injector.inject(http_request, raw_query)
    response_text   = await _call_llm(augmented_query, intent)
    logger.info("LLM response returned.", extra={"intent": intent})
    return {
        "status":     "completed",
        "intent":     intent,
        "confidence": confidence,
        "response":   response_text,
    }


app.include_router(router)
app.include_router(tasks_router)
app.include_router(admin_router)
app.include_router(metrics_router)

# ──────────────────────────────────────────────────────────────
# 8. Helpers
# ──────────────────────────────────────────────────────────────
def _extract_ticker(query: str) -> str:
    """
    Extract a stock ticker from the query.
    Prefers $TICKER notation, then falls back to 1-5 uppercase-letter words.
    Returns "SPY" if nothing found.
    """
    dollar_match = re.search(r'\$([A-Z]{1,5})\b', query)
    if dollar_match:
        return dollar_match.group(1)

    words = re.findall(r'\b([A-Z]{1,5})\b', query)
    _stop = {"I", "A", "AI", "US", "CEO", "CTO", "ETF", "IPO", "API", "DTE"}
    candidates = [w for w in words if w not in _stop]
    return candidates[0] if candidates else "SPY"


async def _call_llm(prompt: str, intent: str) -> str:
    model = (
        os.getenv("CODE_MODEL", "gpt-4o")
        if intent == "code_assistant"
        else settings.DEFAULT_FAST_MODEL
    )
    try:
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("LiteLLM call failed.", extra={"model": model, "error": str(e)})
        raise


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
