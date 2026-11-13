# Built from the repository root, not backend/, so the frontend's static export can be
# baked in and served by the same process as the API:
#   docker build -f backend/Dockerfile .

# Match dagger/socket-firewall's verified release artifacts. The native frontend
# stage and target Python stage need different binaries during cross-platform builds.
FROM scratch AS socket-amd64
ADD https://github.com/SocketDev/sfw-free/releases/download/v1.16.0/sfw-free-linux-x86_64 /sfw

FROM scratch AS socket-arm64
ADD https://github.com/SocketDev/sfw-free/releases/download/v1.16.0/sfw-free-linux-arm64 /sfw

FROM socket-${BUILDARCH} AS socket-build
FROM socket-${TARGETARCH} AS socket-target

# Static output is platform-independent, so pin to BUILDPLATFORM and build it once
# rather than emulating the whole Node toolchain for each target architecture.
FROM --platform=$BUILDPLATFORM ghcr.io/pnpm/pnpm:12.18.0@sha256:41c39d1c734b0a810669c07587888aa7dbe9ef9b4c8e98b346b3654f7b269b6d AS pnpm

FROM --platform=$BUILDPLATFORM node:26.13.1-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend

WORKDIR /src

COPY --from=pnpm /opt/pnpm /opt/pnpm
COPY --from=socket-build --chmod=0755 /sfw /usr/local/bin/sfw
COPY dagger/socket-firewall/src/socket_firewall/checksums.sha256 /tmp/sfw-checksums

ENV PNPM_HOME="/pnpm" \
    PATH="/opt/pnpm:/pnpm:$PATH"

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    checksum="$(sha256sum /usr/local/bin/sfw | cut -d ' ' -f1)" && \
    awk '{print $1}' /tmp/sfw-checksums | grep -Fx "$checksum" && \
    sfw pnpm install --frozen-lockfile

COPY frontend/ /src

# No build args: sign-in is driven entirely by the backend's /api/auth endpoints, so the
# export carries no client ID and is identical for every environment.
# Preserve compiler state across source edits; static output remains in /src/out.
RUN --mount=type=cache,id=agents-nextjs-build,target=/src/.next/cache,sharing=locked \
    pnpm run build


# Build with the same Python minor and distribution as the runtime image.
FROM cgr.dev/chainguard/python:latest-dev@sha256:65e7c280762822c7f8542415e1c7f47e0bf5ea55ed5e656e9e697bf9648f9882 AS builder

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /usr/local/bin/uv
COPY --from=socket-target --chmod=0755 /sfw /usr/local/bin/sfw
COPY dagger/socket-firewall/src/socket_firewall/checksums.sha256 /tmp/sfw-checksums

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Keep the workspace layout while resolving, but install only backend dependencies.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY cli/pyproject.toml cli/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    checksum="$(sha256sum /usr/local/bin/sfw | cut -d ' ' -f1)" && \
    awk '{print $1}' /tmp/sfw-checksums | grep -Fx "$checksum" && \
    sfw uv sync --locked --package agents --no-dev --no-install-workspace

FROM cgr.dev/chainguard/python:latest@sha256:1d151c8e2ec4e140203cab56b4f18e7e3d4dbda07891550cc22f3a06d1801f96

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
