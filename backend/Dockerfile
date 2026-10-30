# Built from the repository root, not backend/, so the frontend's static export can be
# baked in and served by the same process as the API:
#   docker build -f backend/Dockerfile .

# Static output is platform-independent, so pin to BUILDPLATFORM and build it once
# rather than emulating the whole Node toolchain for each target architecture.
FROM --platform=$BUILDPLATFORM node:24.22.1-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS frontend

WORKDIR /src

ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH"

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY frontend/ /src

# No build args: sign-in is driven entirely by the backend's /api/auth endpoints, so the
# export carries no client ID and is identical for every environment.
RUN pnpm run build


# Build with the same Python minor and distribution as the runtime image.
FROM cgr.dev/chainguard/python:latest-dev@sha256:157a562dbc225a2a9039dbd8249cbf704202260ba27bf525f24e47a3a685050f AS builder

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Keep the workspace layout while resolving, but install only backend dependencies.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY cli/pyproject.toml cli/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package agents --no-dev --no-install-workspace

FROM cgr.dev/chainguard/python:latest@sha256:35d6025b288eb1c40ae631db77ed6cdd26c6f51d898428d8fc9989db7f29e784

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --chown=nonroot:nonroot backend/ /app

# Where main.py's STATIC_DIR looks by default
COPY --from=frontend --chown=nonroot:nonroot /src/out /app/static

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER nonroot

ENTRYPOINT ["/app/.venv/bin/uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8080"]
