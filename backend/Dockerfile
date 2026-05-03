FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Repoint venv Python symlinks to /usr/bin/python, where Chainguard places it
RUN ln -sfn /usr/bin/python /app/.venv/bin/python && \
    ln -sfn /usr/bin/python /app/.venv/bin/python3 && \
    ln -sfn /usr/bin/python /app/.venv/bin/python3.14


FROM cgr.dev/chainguard/python:latest@sha256:7b27b4bfa2836f4c7007238658754d94a06ba84461a7720f2e07e284c6e564a1

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app /app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

ENTRYPOINT ["/app/.venv/bin/uvicorn"]
CMD ["main:app", "--host", "0.0.0.0", "--port", "8080"]
