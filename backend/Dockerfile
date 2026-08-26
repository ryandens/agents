# Built from the repository root, not backend/, so the frontend's static export can be
# baked in and served by the same process as the API:
#   docker build -f backend/Dockerfile .

# Static output is platform-independent, so pin to BUILDPLATFORM and build it once
# rather than emulating the whole Node toolchain for each target architecture.
FROM --platform=$BUILDPLATFORM node:24.19.0-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS frontend

WORKDIR /src

COPY frontend/package.json frontend/package-lock.json ./

RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY frontend/ /src

# No build args: sign-in is driven entirely by the backend's /api/auth endpoints, so the
# export carries no client ID and is identical for every environment.
RUN npm run build


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


FROM cgr.dev/chainguard/python:latest@sha256:ee37f5e4fb445732409626797dccb6f2a6337872def2bab48729ee61b335fa77

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app /app

# Where main.py's STATIC_DIR looks by default
COPY --from=frontend --chown=nonroot:nonroot /src/out /app/static

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

ENTRYPOINT ["/app/.venv/bin/uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8080"]
