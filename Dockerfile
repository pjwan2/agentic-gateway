# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────
# Stage 1: builder — install Python deps in an isolated layer
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System libraries required by asyncpg (libpq) and numpy (gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ──────────────────────────────────────────────────────────────
# Stage 2: runtime image — lean, no build tools
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime-only system deps (libpq for asyncpg, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# ── Embedding model cache ─────────────────────────────────────
# Pre-download BAAI/bge-small-en-v1.5 during image build so the
# container starts in ~2 s instead of ~30 s (model = ~130 MB).
# The model is baked into the image layer — no runtime download needed.
ENV SENTENCE_TRANSFORMERS_HOME=/app/.model_cache
ENV HF_HOME=/app/.model_cache

RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); \
print('Embedding model pre-loaded.')"

# ── Security: non-root user ───────────────────────────────────
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8000

# Deep health check — hits the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:8000/health | python3 -c \
        "import sys, json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ok' else 1)"

# Production entry point — single worker; scale horizontally via replicas
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-config", "/dev/null"]
