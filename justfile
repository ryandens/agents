set dotenv-load := true

# List available recipes
default:
    @just --list

# ── Dev ────────────────────────────────────────────────────────────────────────

# Write .env from 1Password (needs the `op` CLI, signed in)
env-sync:
    #!/usr/bin/env bash
    set -euo pipefail

    oauth_item="${OP_OAUTH_ITEM:-agents.ryandens.com}"
    api_key_item="${OP_API_KEY_ITEM:-Claude API Key}"

    client_id="$(op item get "$oauth_item" --fields label=client_id --reveal)"
    if [ -z "$client_id" ]; then
        echo "error: no client_id on 1Password item '$oauth_item'" >&2
        exit 1
    fi

    # The API key item's field label varies by category, so try the usual ones rather
    # than hardcoding one. Missing is not fatal — only the chat agent needs it.
    api_key=""
    for label in credential password "api key" apiKey; do
        if api_key="$(op item get "$api_key_item" --fields "label=$label" --reveal 2>/dev/null)" && [ -n "$api_key" ]; then
            break
        fi
        api_key=""
    done

    # Preserve existing ANTHROPIC_API_KEY from .env if 1Password lookup failed.
    existing_api_key=""
    if [ -z "$api_key" ] && [ -f .env ]; then
        existing_api_key="$(grep -E '^ANTHROPIC_API_KEY=' .env 2>/dev/null | sed 's/^ANTHROPIC_API_KEY=//' || true)"
    fi

    # umask only covers a file this creates, so chmod below handles an existing .env too.
    umask 077
    {
        echo "# Written by \`just env-sync\` from 1Password. Gitignored — do not commit."
        echo ""
        echo "# Verified by the backend, and mirrored to NEXT_PUBLIC_GOOGLE_CLIENT_ID for the browser."
        echo "GOOGLE_CLIENT_ID=$client_id"
        echo ""
        if [ -n "$api_key" ]; then
            echo "ANTHROPIC_API_KEY=$api_key"
        elif [ -n "$existing_api_key" ]; then
            echo "ANTHROPIC_API_KEY=$existing_api_key"
        else
            echo "# Not found on 1Password item '$api_key_item' — set OP_API_KEY_ITEM or fill in by hand."
            echo "# ANTHROPIC_API_KEY="
        fi
    } > .env
    chmod 600 .env

    echo "wrote .env: GOOGLE_CLIENT_ID from '$oauth_item'"
    if [ -n "$api_key" ]; then
        echo "            ANTHROPIC_API_KEY from '$api_key_item'"
    elif [ -n "$existing_api_key" ]; then
        echo "            ANTHROPIC_API_KEY preserved from existing .env"
    else
        echo "            ANTHROPIC_API_KEY missing — chat will not work until it is set" >&2
    fi

# Start both dev servers with live reload — open http://localhost:3000
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    # Next proxies /api to the backend, so :3000 mirrors production's single origin.
    # Job control puts each server in its own process group, so the trap can take down
    # uvicorn's reloader and next's workers rather than orphaning them.
    set -m
    {{ just_executable() }} backend-dev &
    backend=$!
    {{ just_executable() }} frontend-dev &
    frontend=$!
    trap 'kill -- -$backend -$frontend 2>/dev/null || true' EXIT INT TERM
    wait

# Stop dev servers left listening on :3000/:8000 (when `just dev`'s trap didn't fire)
dev-stop:
    #!/usr/bin/env bash
    set -uo pipefail

    # Kill by process group, not PID: uvicorn's reloader and next dev each fork workers
    # that keep the port bound if only the parent goes. `just dev` puts each server in
    # its own group, so the group is exactly one server and nothing else.
    groups() {
        local pids
        pids="$(lsof -t -nP -iTCP:3000 -iTCP:8000 -sTCP:LISTEN 2>/dev/null)" || true
        [ -n "$pids" ] || return 0
        # shellcheck disable=SC2086 # deliberate word splitting: one -p flag, many pids
        ps -o pgid= -p $pids 2>/dev/null | tr -d ' ' | sort -u
    }

    pgids="$(groups)"
    if [ -z "$pgids" ]; then
        echo "nothing listening on :3000 or :8000"
        exit 0
    fi

    self="$(ps -o pgid= -p $$ | tr -d ' ')"
    for pgid in $pgids; do
        [ "$pgid" = "$self" ] && continue # don't take down this recipe
        kill -TERM -- "-$pgid" 2>/dev/null || true
    done

    # Give them a moment to shut down cleanly before escalating.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [ -z "$(groups)" ] && break
        sleep 0.5
    done

    for pgid in $(groups); do
        [ "$pgid" = "$self" ] && continue
        kill -KILL -- "-$pgid" 2>/dev/null || true
    done

    if [ -n "$(groups)" ]; then
        echo "still listening on :3000 or :8000:" >&2
        lsof -nP -iTCP:3000 -iTCP:8000 -sTCP:LISTEN >&2
        exit 1
    fi
    echo "stopped dev servers on :3000 and :8000"

# Build the frontend into backend/static, where the app serves it from
build: frontend-build
    rm -rf backend/static
    cp -R frontend/out backend/static

# Serve the built frontend and API from one origin at http://localhost:8000, as production does
serve: build
    uv run --project backend uvicorn main:app --app-dir backend --port 8000

# Build the production image (frontend export + API in one container)
docker-build:
    docker build -f backend/Dockerfile -t agents:local \
        --build-arg NEXT_PUBLIC_GOOGLE_CLIENT_ID="${NEXT_PUBLIC_GOOGLE_CLIENT_ID:-${GOOGLE_CLIENT_ID:-}}" .

# Smoke-test an already-built image (CI passes the tag it just built)
smoke image="agents:local" port="8080":
    #!/usr/bin/env bash
    set -euo pipefail
    name="agents-smoke-{{ port }}"
    docker rm -f "$name" >/dev/null 2>&1 || true

    cleanup() {
        rc=$?
        if [ "$rc" -ne 0 ]; then
            echo "--- container logs ---" >&2
            docker logs "$name" 2>&1 | tail -40 >&2 || true
        fi
        docker rm -f "$name" >/dev/null 2>&1 || true
        exit "$rc"
    }
    trap cleanup EXIT

    docker run -d --name "$name" -p {{ port }}:8080 -e GOOGLE_CLIENT_ID=smoke-test {{ image }} >/dev/null
    python3 scripts/smoke_test.py "http://127.0.0.1:{{ port }}"

# Build the production image and smoke-test it
docker-check: docker-build smoke

# Run the production image at http://localhost:8080
docker-run: docker-build
    docker run --rm -p 8080:8080 \
        -e ANTHROPIC_API_KEY \
        -e GOOGLE_CLIENT_ID \
        -v "$PWD/backend/data:/app/data" \
        agents:local

# Remove build output
clean:
    rm -rf backend/static frontend/out frontend/.next

# ── Backend ────────────────────────────────────────────────────────────────────

# Install backend dependencies
backend-install:
    uv sync --dev --project backend

# Start backend dev server on :8000 (also serves backend/static if `just build` ran)
backend-dev:
    uv run --project backend uvicorn main:app --app-dir backend --reload --port 8000

# Run backend linter (scripts/ holds the smoke test, held to the same standard)
backend-lint:
    uv run --project backend ruff check backend scripts

# Run backend format check
backend-fmt:
    uv run --project backend ruff format --check backend scripts

# Run backend tests
backend-test:
    uv run --project backend pytest backend

# Run all backend checks
backend-check: backend-lint backend-fmt backend-test

# ── Frontend ───────────────────────────────────────────────────────────────────

# Install frontend dependencies
frontend-install:
    npm install --prefix frontend

# Start frontend dev server on :3000, proxying /api to the backend on :8000
frontend-dev:
    #!/usr/bin/env bash
    set -euo pipefail
    # The backend reads GOOGLE_CLIENT_ID from .env; the browser needs the same value
    # under the NEXT_PUBLIC_ prefix. Anything already set (frontend/.env.local) wins.
    if [ -z "${NEXT_PUBLIC_GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_ID:-}" ]; then
        export NEXT_PUBLIC_GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID"
    fi
    npm run dev --prefix frontend

# Run frontend linter
frontend-lint:
    npm run lint --prefix frontend

# Build frontend (type check + compile)
frontend-build:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "${NEXT_PUBLIC_GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_ID:-}" ]; then
        export NEXT_PUBLIC_GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID"
    fi
    npm run build --prefix frontend

# Run frontend tests
frontend-test:
    npm run test --prefix frontend

# Run all frontend checks
frontend-check: frontend-lint frontend-build frontend-test

# ── CI ─────────────────────────────────────────────────────────────────────────

# Run all checks (mirrors CI)
check: backend-check frontend-check
