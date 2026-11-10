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

FROM --platform=$BUILDPLATFORM node:26.13.0-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS frontend

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
RUN pnpm run build


# Build with the same Python minor and distribution as the runtime image.
FROM cgr.dev/chainguard/python:latest-dev@sha256:62c16c709c48c8e66647c843b5aceeac81d4523134c742bc017a46f5a86ba5dd AS builder

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
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

FROM cgr.dev/chainguard/python:latest@sha256:c932048a3f1db1fecefbd589d4fb90bf1d364b4c1ebd9aa8c866f29bb93e88cc

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
