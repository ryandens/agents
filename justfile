set dotenv-load := true

# List available recipes
default:
    @just --list

# ── Dev ────────────────────────────────────────────────────────────────────────

# Start both backend and frontend dev servers
dev:
    just backend-dev & just frontend-dev

# ── Backend ────────────────────────────────────────────────────────────────────

# Install backend dependencies
backend-install:
    uv sync --dev --project backend

# Start backend dev server
backend-dev:
    uv run --project backend uvicorn main:app --app-dir backend --reload --port 8000

# Run backend linter
backend-lint:
    uv run --project backend ruff check backend

# Run backend format check
backend-fmt:
    uv run --project backend ruff format --check backend

# Run all backend checks
backend-check: backend-lint backend-fmt

# ── Frontend ───────────────────────────────────────────────────────────────────

# Install frontend dependencies
frontend-install:
    npm install --prefix frontend

# Start frontend dev server
frontend-dev:
    npm run dev --prefix frontend

# Run frontend linter
frontend-lint:
    npm run lint --prefix frontend

# Build frontend (type check + compile)
frontend-build:
    npm run build --prefix frontend

# Run all frontend checks
frontend-check: frontend-lint frontend-build

# ── CI ─────────────────────────────────────────────────────────────────────────

# Run all checks (mirrors CI)
check: backend-check frontend-check
