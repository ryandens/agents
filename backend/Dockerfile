# Built from the repository root, not backend/, so the frontend's static export can be
# baked in and served by the same process as the API:
#   docker build -f backend/Dockerfile .

# Static output is platform-independent, so pin to BUILDPLATFORM and build it once
# rather than emulating the whole Node toolchain for each target architecture.
FROM --platform=$BUILDPLATFORM node:24.21.0-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS frontend

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
FROM cgr.dev/chainguard/python:latest-dev@sha256:10b20ac005729c71a48ad6232c726527274959aec1e5e9ebae4ac86745b4c078 AS builder

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

COPY backend/ /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM cgr.dev/chainguard/python:latest@sha256:5d7edd76101b0b8112b723072125f428dbfd291d7cc56a6418a5f619023e2542

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app /app

# Where main.py's STATIC_DIR looks by default
COPY --from=frontend --chown=nonroot:nonroot /src/out /app/static

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER nonroot

ENTRYPOINT ["/app/.venv/bin/uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8080"]
