# core/config.py
import os


def _require_env(key: str, dev_default: str) -> str:
    """
    Return the env var value, or the dev default in local mode.
    Raises in production if the variable is unset — prevents misconfigured deploys.
    """
    value = os.getenv(key)
    if value:
        return value
    if os.getenv("ENV", "development") == "production":
        raise RuntimeError(f"Required environment variable '{key}' is not set.")
    return dev_default


class Settings:
    # ── Runtime environment ───────────────────────────────────
    ENV: str = os.getenv("ENV", "development")   # "development" | "production"

    # ── Infrastructure ────────────────────────────────────────
    REDIS_URL:          str = _require_env("REDIS_URL",          "redis://localhost:6379/0")
    CELERY_BACKEND_URL: str = _require_env("CELERY_BACKEND_URL", "redis://localhost:6379/1")
    POSTGRES_URL:       str = _require_env("POSTGRES_URL",       "postgresql://admin:password@localhost:5432/deeprouter")

    # ── LiteLLM — provider-agnostic model routing ─────────────
    DEFAULT_FAST_MODEL: str = os.getenv("DEFAULT_FAST_MODEL", "gpt-4o-mini")
    CODE_MODEL:         str = os.getenv("CODE_MODEL",         "gpt-4o")
    LITELLM_API_KEY:    str = _require_env("LITELLM_API_KEY",  "sk-dev-placeholder")

    # ── Authentication ────────────────────────────────────────
    DEV_API_KEY:  str = os.getenv("DEV_API_KEY", "dev-secret-key")

    # ── Admin API ─────────────────────────────────────────────
    # X-Admin-Secret header value — separate namespace from user keys
    ADMIN_SECRET: str = _require_env("ADMIN_SECRET", "admin-dev-secret")
    # Comma-separated IPs / CIDRs allowed to call /admin/v1/*
    # Ignored in development mode (ENV=development)
    ADMIN_ALLOWED_IPS: str = os.getenv("ADMIN_ALLOWED_IPS", "127.0.0.1,::1")

    # ── Observability ─────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Rate limiting ─────────────────────────────────────────
    MAX_TPM: int = int(os.getenv("MAX_TPM", "6000"))


settings = Settings()
