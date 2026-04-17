# Contributing to DeepRouter

Thank you for your interest in contributing. This document covers everything you need to get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Report a Bug](#how-to-report-a-bug)
- [How to Request a Feature](#how-to-request-a-feature)
- [Development Setup](#development-setup)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Coding Standards](#coding-standards)
- [Commit Message Format](#commit-message-format)

---

## Code of Conduct

Be respectful. Constructive criticism is welcome; personal attacks are not. Maintainers reserve the right to close issues or PRs that violate this principle.

---

## How to Report a Bug

1. Search [existing issues](https://github.com/pjwan2/agentic-gateway/issues) first.
2. If not found, open a new issue using the **Bug Report** template.
3. Include: Python version, OS, steps to reproduce, expected vs. actual behavior, and relevant log output (redact any API keys).

---

## How to Request a Feature

Open an issue using the **Feature Request** template. Describe the problem you're trying to solve — not just the solution. This helps maintainers understand the use-case and propose the right design.

---

## Development Setup

**Requirements:** Python 3.12, Docker, Docker Compose, Redis, PostgreSQL with pgvector.

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/agentic-gateway.git
cd agentic-gateway

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env            # Edit as needed

# 5. Apply database migrations
psql $POSTGRES_URL -f migrations/001_initial_schema.sql

# 6. Start the dev server
uvicorn main:app --reload --port 8003

# 7. (Separate terminal) Start Celery worker
celery -A workers.celery_worker worker --pool=solo --loglevel=info
```

---

## Submitting a Pull Request

1. Create a branch from `main`: `git checkout -b feat/your-feature`
2. Make your changes. Keep commits focused (one logical change per commit).
3. Run the fast unit tests: `pytest tests/unit --fast -v`
4. Run the linter: `ruff check .`
5. Push your branch and open a PR against `main` using the PR template.
6. Ensure the CI pipeline passes before requesting review.

PRs that fail linting or tests will not be merged.

---

## Coding Standards

- **Style**: enforced by `ruff`. Run `ruff check .` before committing.
- **Type hints**: use Python 3.12 built-in generics (`list[str]`, `dict[str, Any]`, `tuple[str, float]`) — not `typing.List` etc.
- **Async**: prefer `async/await` throughout. Do not block the event loop with synchronous I/O.
- **Error handling**: raise `HTTPException` at API boundaries. Do not swallow exceptions silently.
- **Secrets**: never commit real API keys, passwords, or certificates. The `.gitignore` excludes `.env` and `nginx/certs/` — keep it that way.

---

## Commit Message Format

```
<type>(<scope>): <short summary>

[optional body — explain *why*, not *what*]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`

Examples:
```
feat(router): return confidence score alongside intent classification
fix(auth): use request.state.user_id instead of spoofable header
docs(readme): replace placeholder your-org with pjwan2
```
