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
FROM --platform=$BUILDPLATFORM ghcr.io/pnpm/pnpm:12.21.0@sha256:168feba88e6a1684c99a62cbf4fe361d4e683e2a6c920d3b0acde7e15a28b62d AS pnpm

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
FROM cgr.dev/chainguard/python:latest-dev@sha256:e0df0ab3cb72380c82f8c5513538152e822a6d8994252663060adea9fdc450c2 AS builder

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

FROM cgr.dev/chainguard/python:latest@sha256:b969ffa5d847b5acd28bd18b12d5b6631cb69c8289f03b309e19b68608724dc6

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
