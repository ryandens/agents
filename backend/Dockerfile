# Built from the repository root, not backend/, so the frontend's static export can be
# baked in and served by the same process as the API:
#   docker build -f backend/Dockerfile .

# Static output is platform-independent, so pin to BUILDPLATFORM and build it once
# rather than emulating the whole Node toolchain for each target architecture.
FROM --platform=$BUILDPLATFORM node:24.20.0-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS frontend

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


FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

COPY backend/ /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Repoint venv Python symlinks to /usr/bin/python, where Chainguard places it
RUN ln -sfn /usr/bin/python /app/.venv/bin/python && \
    ln -sfn /usr/bin/python /app/.venv/bin/python3 && \
    ln -sfn /usr/bin/python /app/.venv/bin/python3.14


FROM cgr.dev/chainguard/python:latest@sha256:13c56985fd39c738ef28e372f533ef2a80659d768443f0725fe48080408f8e6a

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app /app

# Where main.py's STATIC_DIR looks by default
COPY --from=frontend --chown=nonroot:nonroot /src/out /app/static

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER nonroot

ENTRYPOINT ["/app/.venv/bin/uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8080"]
