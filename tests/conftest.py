# tests/conftest.py
"""
Shared pytest fixtures and configuration.

Environment variables are set before any application module is imported
so Settings() reads the test values instead of requiring a real .env file.
"""
import os
import pytest

# ── Set test environment BEFORE any app import ────────────────
os.environ.setdefault("ENV",                  "development")
os.environ.setdefault("REDIS_URL",            "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BACKEND_URL",   "redis://localhost:6379/1")
os.environ.setdefault("POSTGRES_URL",         "postgresql://admin:password@localhost:5432/deeprouter")
os.environ.setdefault("LITELLM_API_KEY",      "sk-test-placeholder")
os.environ.setdefault("ADMIN_SECRET",         "test-admin-secret")
os.environ.setdefault("DEV_API_KEY",          "test-dev-key")
os.environ.setdefault("DEFAULT_FAST_MODEL",   "gpt-4o-mini")


# ── Custom CLI flags ──────────────────────────────────────────
def pytest_addoption(parser):
    parser.addoption(
        "--fast",
        action="store_true",
        default=False,
        help="Skip slow tests that load ML models or perform heavy I/O.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: marks tests that load ML models or require external services",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--fast"):
        skip = pytest.mark.skip(reason="Skipped via --fast flag")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip)
