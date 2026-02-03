-- migrations/001_initial_schema.sql
-- Run once against the deeprouter database:
--   psql $POSTGRES_URL -f migrations/001_initial_schema.sql

-- Enable pgvector extension (already available in ankane/pgvector image)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- user_memories
-- Stores the long-term profile summary injected into every LLM
-- call for a given user. Updated by a background summarizer job.
-- ============================================================
CREATE TABLE IF NOT EXISTS user_memories (
    user_id         TEXT        PRIMARY KEY,
    profile_summary TEXT        NOT NULL DEFAULT '',
    embedding       vector(384),          -- BAAI/bge-small-en-v1.5 dimension
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_memories_updated
    ON user_memories (updated_at DESC);

-- ANN index for future semantic memory search
CREATE INDEX IF NOT EXISTS idx_user_memories_embedding
    ON user_memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- api_keys
-- Stores hashed API keys for user authentication.
-- The raw key is NEVER stored — only SHA-256(raw_key).
-- AuthMiddleware also writes these to Redis for fast lookup;
-- this table is the authoritative source of truth.
-- ============================================================
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    TEXT        PRIMARY KEY,          -- SHA-256(raw_key), hex-encoded
    user_id     TEXT        NOT NULL,
    label       TEXT        NOT NULL DEFAULT '',  -- human-readable name, e.g. "prod-frontend"
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,                      -- NULL = no expiry
    revoked     BOOLEAN     NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys (user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_expires  ON api_keys (expires_at) WHERE expires_at IS NOT NULL;
