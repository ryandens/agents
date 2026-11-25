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

FROM --platform=$BUILDPLATFORM node:26.13.1-slim@sha256:abe7e5a82b61a8ef67b315b85497c9e65173387ccf2f4a029248184b8e020be5 AS frontend

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
FROM cgr.dev/chainguard/python:latest-dev@sha256:768ee36ee9f4b8c882634c07d0b889425bc8e100886a3f742b83b1c647cc2d4b AS builder

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /usr/local/bin/uv
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

FROM cgr.dev/chainguard/python:latest@sha256:f522a16f34c8aa60f831e6476e396ef3951830a1b9059d19bc531a544d0f1579

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
