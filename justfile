set dotenv-load := true

# The local development database. The major version matches the Aurora PostgreSQL
# cluster in infrastructure/rds.tf and the container backend/conftest.py starts for
# tests, so development, tests and production all run the same engine.
postgres_image := "postgres:17-alpine"
db_container := "agents-postgres"
db_port := "5432"
db_url := "postgresql://agents:agents@127.0.0.1:" + db_port + "/agents"

# List available recipes
default:
    @just --list

# ── Dev ────────────────────────────────────────────────────────────────────────

# Write .env and infrastructure/terraform.tfvars from 1Password (needs the `op` CLI, signed in)
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

    # `|| true` so a missing field reaches the check below rather than tripping `set -e`
    # and exiting with op's error instead of this one.
    client_secret="$(op item get "$oauth_item" --fields label=client_secret --reveal 2>/dev/null || true)"
    if [ -z "$client_secret" ]; then
        echo "error: no client_secret on 1Password item '$oauth_item'" >&2
        echo "       add it as a field named 'client_secret' (Google console → OAuth client)" >&2
        exit 1
    fi

    # Who may sign in. Google does not enforce its test-user list for openid/email/profile
    # apps, so without this the app is open to every Google account.
    allowed_emails="$(op item get "$oauth_item" --fields label=allowed_emails --reveal 2>/dev/null || true)"

    # First non-empty field among several candidate labels. Fields inside a 1Password
    # section are addressed by label like any other, so this does not need to know which
    # section holds them — only what the label might be called.
    op_field() {
        local item="$1" label value
        shift
        for label in "$@"; do
            if value="$(op item get "$item" --fields "label=$label" --reveal 2>/dev/null)" && [ -n "$value" ]; then
                printf '%s' "$value"
                return 0
            fi
        done
        return 1
    }

    # Reuse whatever is already in .env for the values that are not in 1Password, so
    # re-running this does not silently sign everyone out or lock everyone out.
    read_env() {
        [ -f .env ] && grep -E "^$1=" .env 2>/dev/null | head -1 | sed "s/^$1=//" || true
    }

    tfvars="infrastructure/terraform.tfvars"

    # Same idea as read_env, for the deploy-side values that are not in 1Password.
    # Only handles `name = "value"` — every string variable this recipe writes — and
    # returns the literal source text, so a value carrying HCL escapes would come back
    # still escaped. None of what it reads (a tag@digest, an API key, a tailnet name, a
    # hostname, a tskey-auth-… key) can.
    read_tfvars() {
        [ -f "$tfvars" ] && sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\\(.*\\)\"[[:space:]]*\$/\\1/p" "$tfvars" | head -1 || true
    }

    # Escape a value for an HCL double-quoted string. Terraform evaluates ${...} and
    # %{...} inside one, so those markers are doubled rather than passed through.
    hcl() {
        printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\${/$${/g' -e 's/%{/%%{/g'
    }

    if [ -z "$allowed_emails" ]; then
        allowed_emails="$(read_env ALLOWED_EMAILS)"
    fi

    # Normalize to a bare comma-separated list, and build the list(string) form the
    # terraform variable wants from the same entries. The backend strips whitespace
    # itself, but `set dotenv-load` does not: a space in the .env value makes just
    # refuse to run *any* recipe, so a spaced 1Password field would leave the next
    # `just env-sync` unable to start and the allowlist unfixable through this recipe.
    allowed_emails_hcl=""
    normalized_emails=""
    if [ -n "$allowed_emails" ]; then
        IFS=',' read -ra raw_emails <<< "$allowed_emails"
        for email in "${raw_emails[@]}"; do
            email="$(printf '%s' "$email" | tr -d '[:space:]')"
            [ -n "$email" ] || continue
            normalized_emails="${normalized_emails:+$normalized_emails,}$email"
            allowed_emails_hcl="${allowed_emails_hcl:+$allowed_emails_hcl, }\"$(hcl "$email")\""
        done
    fi
    allowed_emails="$normalized_emails"

    # Machine callers. Not in 1Password — this is granted by hand — so it is carried over
    # from the previous .env, which stops a re-run from silently revoking it. .env is the
    # only place it is preserved from: read_tfvars understands `name = "value"` and this
    # is a list. Same whitespace stripping as above, for the same `set dotenv-load` reason.
    allowed_service_accounts=""
    service_accounts_hcl=""
    previous_service_accounts="$(read_env ALLOWED_SERVICE_ACCOUNTS)"
    if [ -n "$previous_service_accounts" ]; then
        IFS=',' read -ra raw_service_accounts <<< "$previous_service_accounts"
        for service_account in "${raw_service_accounts[@]}"; do
            service_account="$(printf '%s' "$service_account" | tr -d '[:space:]')"
            [ -n "$service_account" ] || continue
            allowed_service_accounts="${allowed_service_accounts:+$allowed_service_accounts,}$service_account"
            service_accounts_hcl="${service_accounts_hcl:+$service_accounts_hcl, }\"$(hcl "$service_account")\""
        done
    fi

    # Where the local backend keeps the pantry. Not in 1Password and not a secret, but
    # preserved from an existing .env so anyone pointing their dev server at a different
    # database does not get it reset from under them on the next sync.
    database_url="$(read_env DATABASE_URL)"
    database_url="${database_url:-{{ db_url }}}"

    # Signs the session cookie. Generated once and then preserved — regenerating it
    # invalidates every existing session.
    session_secret="$(read_env SESSION_SECRET)"
    if [ -z "$session_secret" ]; then
        session_secret="$(openssl rand -base64 32)"
    fi

    # Drives the redirect URI. Overridable because `just serve` (:8000) and `just
    # docker-run` (:8080) are not on the dev server's port, and Google matches the
    # redirect URI exactly. An existing .env wins over the default so re-running keeps
    # whatever was chosen.
    app_base_url="${APP_BASE_URL:-$(read_env APP_BASE_URL)}"
    app_base_url="${app_base_url:-http://localhost:3000}"
    app_base_url="${app_base_url%/}"
    redirect_uri="$app_base_url/api/auth/callback"

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

    # ── Deploy-side values, for infrastructure/terraform.tfvars ────────────────

    # Names the image to deploy and changes every release, so it lives nowhere but the
    # tfvars file. Carried over so re-running this does not roll production back to a
    # prompt — terraform has no default for it.
    app_version="$(read_tfvars app_version)"

    # Tailscale is the deployed app's only way in, so these are deploy-side only — none
    # of them belong in .env, where nothing reads them.
    #
    # The labels are guesses across the plausible spellings, because 1Password does not
    # constrain what a field in the tailscale section is called. A miss is not fatal: the
    # value falls back to the previous terraform.tfvars and then to a commented-out line,
    # the same way a missing API key does, rather than blanking out a working config.
    ts_key_labels="tailscale_auth_key, auth_key, authkey, 'tailscale auth key'"
    ts_net_labels="tailscale_tailnet, tailnet, tailnet_name, 'tailscale tailnet'"
    tailscale_auth_key="$(op_field "$oauth_item" tailscale_auth_key auth_key authkey "tailscale auth key" || true)"
    tailscale_tailnet="$(op_field "$oauth_item" tailscale_tailnet tailnet tailnet_name "tailscale tailnet" || true)"
    # No label loop worth widening here: tailscale_hostname is the one tailscale variable
    # terraform defaults ("agents"), so an unfound value is the normal case, not a miss.
    tailscale_hostname="$(op_field "$oauth_item" tailscale_hostname || true)"

    if [ -z "$tailscale_auth_key" ]; then
        tailscale_auth_key="$(read_tfvars tailscale_auth_key)"
    fi
    if [ -z "$tailscale_tailnet" ]; then
        tailscale_tailnet="$(read_tfvars tailscale_tailnet)"
    fi
    if [ -z "$tailscale_hostname" ]; then
        tailscale_hostname="$(read_tfvars tailscale_hostname)"
    fi

    # Third place the key may already be, after 1Password and .env — also no default in
    # terraform, so a failed lookup must not blank it out.
    tf_api_key="$api_key"
    if [ -z "$tf_api_key" ]; then
        tf_api_key="${existing_api_key:-$(read_tfvars anthropic_api_key)}"
    fi

    # umask only covers a file this creates, so chmod below handles an existing .env too.
    umask 077
    {
        echo "# Written by \`just env-sync\` from 1Password. Gitignored — do not commit."
        echo ""
        echo "# The OIDC client the backend runs the authorization code flow with."
        echo "GOOGLE_CLIENT_ID=$client_id"
        echo "GOOGLE_CLIENT_SECRET=$client_secret"
        echo ""
        echo "# Where Google redirects back to. $redirect_uri must be"
        echo "# registered on the OAuth client as an authorized redirect URI."
        echo "APP_BASE_URL=$app_base_url"
        echo ""
        echo "# Signs the session cookie. Changing it signs everyone out."
        echo "SESSION_SECRET=$session_secret"
        echo ""
        echo "# Comma-separated allowlist. Empty means nobody can sign in."
        if [ -n "$allowed_emails" ]; then
            echo "ALLOWED_EMAILS=$allowed_emails"
        else
            echo "# No 'allowed_emails' field on '$oauth_item' and none in the previous .env."
            echo "ALLOWED_EMAILS="
        fi
        echo ""
        echo "# Service accounts allowed to call the API with a bearer ID token, for"
        echo "# callers with no browser. Empty means only signed-in people get in."
        echo "ALLOWED_SERVICE_ACCOUNTS=$allowed_service_accounts"
        echo ""
        echo "# The pantry database. Defaults to the container \`just db-up\` starts;"
        echo "# production gets its own from Parameter Store, built from the Aurora"
        echo "# endpoint. Not a secret — the local database is on loopback only."
        echo "DATABASE_URL=$database_url"
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

    # Same values, HCL-shaped, for `terraform apply`. Gitignored by
    # infrastructure/.gitignore (*.tfvars), and holds the same secrets as .env.
    {
        echo "# Written by \`just env-sync\` from 1Password. Gitignored — do not commit."
        echo ""
        if [ -n "$app_version" ]; then
            echo "# Carried over from the previous terraform.tfvars — 1Password does not track it."
            echo "# Bump it by hand to deploy a new build; the instance is replaced on change."
            echo "app_version = \"$(hcl "$app_version")\""
        else
            echo "# No previous terraform.tfvars to carry app_version over from. Set it to the"
            echo "# tag@digest you want deployed, e.g. \"0.1.0@sha256:…\" — terraform prompts"
            echo "# for it on every apply until you do."
            echo "# app_version = \"\""
        fi
        echo ""
        echo "# The OIDC client the backend runs the authorization code flow with."
        echo "google_client_id     = \"$(hcl "$client_id")\""
        echo "google_client_secret = \"$(hcl "$client_secret")\""
        echo ""
        if [ -n "$tf_api_key" ]; then
            echo "anthropic_api_key = \"$(hcl "$tf_api_key")\""
        else
            echo "# Not found on 1Password item '$api_key_item', in .env, or in the previous"
            echo "# terraform.tfvars — terraform prompts for it until it is set."
            echo "# anthropic_api_key = \"\""
        fi
        echo ""
        echo "# The only thing restricting who can use the deployed app."
        if [ -n "$allowed_emails_hcl" ]; then
            echo "allowed_emails = [$allowed_emails_hcl]"
        else
            echo "# No 'allowed_emails' field on '$oauth_item' and none in the previous .env."
            echo "# An empty list fails validation, so fill this in before applying."
            echo "allowed_emails = []"
        fi
        echo ""
        echo "# Machine callers, carried over from .env. An empty list is valid and means"
        echo "# bearer auth stays off."
        echo "allowed_service_accounts = [$service_accounts_hcl]"
        echo ""
        echo "# Joins the tailnet at boot. The deployed app is reachable over Tailscale and"
        echo "# nowhere else, so without this there is no way in at all."
        if [ -n "$tailscale_auth_key" ]; then
            echo "tailscale_auth_key = \"$(hcl "$tailscale_auth_key")\""
        else
            echo "# Not found on '$oauth_item' (tried $ts_key_labels) or in the previous"
            echo "# terraform.tfvars — terraform prompts for it until it is set. Generate a"
            echo "# reusable, ephemeral, pre-approved key at"
            echo "# https://login.tailscale.com/admin/settings/keys."
            echo "# tailscale_auth_key = \"\""
        fi
        echo ""
        echo "# Composes the app's only origin, https://<hostname>.<tailnet> — which is also"
        echo "# the OAuth redirect origin, so it has to match the real MagicDNS name."
        if [ -n "$tailscale_tailnet" ]; then
            echo "tailscale_tailnet = \"$(hcl "$tailscale_tailnet")\""
        else
            echo "# Not found on '$oauth_item' (tried $ts_net_labels) or in the previous"
            echo "# terraform.tfvars — terraform prompts for it until it is set. It is on the"
            echo "# DNS page of the Tailscale admin console, e.g. \"tail1a2b3c.ts.net\"."
            echo "# tailscale_tailnet = \"\""
        fi
        if [ -n "$tailscale_hostname" ]; then
            echo "tailscale_hostname = \"$(hcl "$tailscale_hostname")\""
        else
            echo "# tailscale_hostname left unset — terraform defaults it to \"agents\"."
        fi
    } > "$tfvars"
    chmod 600 "$tfvars"

    echo "wrote .env: GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET from '$oauth_item'"
    if [ -n "$allowed_emails" ]; then
        echo "            ALLOWED_EMAILS=$allowed_emails"
    else
        echo "            ALLOWED_EMAILS empty — sign-in will reject everyone until it is set" >&2
    fi
    if [ -n "$allowed_service_accounts" ]; then
        echo "            ALLOWED_SERVICE_ACCOUNTS=$allowed_service_accounts (preserved)"
    fi
    if [ -n "$api_key" ]; then
        echo "            ANTHROPIC_API_KEY from '$api_key_item'"
    elif [ -n "$existing_api_key" ]; then
        echo "            ANTHROPIC_API_KEY preserved from existing .env"
    else
        echo "            ANTHROPIC_API_KEY missing — chat will not work until it is set" >&2
    fi

    echo "wrote $tfvars"
    if [ -n "$tailscale_auth_key" ] && [ -n "$tailscale_tailnet" ]; then
        echo "            tailscale_auth_key + tailscale_tailnet=$tailscale_tailnet"
        echo "            deployed app will be at https://${tailscale_hostname:-agents}.$tailscale_tailnet"
        echo "            register https://${tailscale_hostname:-agents}.$tailscale_tailnet/api/auth/callback on the OAuth client"
    else
        [ -n "$tailscale_auth_key" ] || echo "            tailscale_auth_key missing — terraform apply cannot reach the tailnet" >&2
        [ -n "$tailscale_tailnet" ] || echo "            tailscale_tailnet missing — terraform apply will prompt for it" >&2
    fi

    echo "wrote $tfvars: same client ID/secret, allowed_emails and API key, HCL-shaped"
    if [ -n "$app_version" ]; then
        echo "            app_version = $app_version (preserved)"
    else
        echo "            app_version unset — terraform will prompt on apply" >&2
    fi

    # Sign-in dies with "Error 400: redirect_uri_mismatch" unless this exact string is
    # registered, and it is easy to miss because the old sign-in flow used the OAuth
    # client's *JavaScript origins* list instead, which the code flow ignores.
    # The client ID's leading digits are the project number, so the link lands on the
    # right project's credentials page.
    echo ""
    echo "Register this exact URI under 'Authorized redirect URIs' on the OAuth client:"
    echo "    $redirect_uri"
    echo "    https://console.cloud.google.com/apis/credentials?project=${client_id%%-*}"

# Start Postgres, apply migrations, and run both dev servers — open http://localhost:3000
dev: db-up db-migrate
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

# ── Database ───────────────────────────────────────────────────────────────────
#
# The pantry lives in Postgres — Aurora in production, a container here. `just dev`
# starts it, so most of the time none of these need running by hand.

# Start the local Postgres on :5432, creating it if it does not exist yet
db-up:
    #!/usr/bin/env bash
    set -euo pipefail

    if [ -z "$(docker ps -q --filter "name=^/{{ db_container }}$")" ]; then
        # Start the existing container if there is one, so a stop/start cycle keeps the
        # data; otherwise create it. A named volume rather than a bind mount, because the
        # data directory has to be owned by the postgres user inside the container and a
        # host directory would arrive owned by whoever ran this.
        docker start {{ db_container }} >/dev/null 2>&1 || docker run -d \
            --name {{ db_container }} \
            -e POSTGRES_USER=agents \
            -e POSTGRES_PASSWORD=agents \
            -e POSTGRES_DB=agents \
            -p 127.0.0.1:{{ db_port }}:5432 \
            -v agents-pgdata:/var/lib/postgresql/data \
            {{ postgres_image }} >/dev/null
    fi

    # `docker run` returns once the container is started, which is well before postgres
    # is accepting connections — without this the backend loses the race on a cold start.
    #
    # -h 127.0.0.1 forces the check over TCP, and that is the whole point rather than a
    # detail. On a first run the entrypoint brings up a temporary server to run initdb
    # and CREATE DATABASE, then shuts it down and starts the real one; a socket check
    # answers "ready" against that temporary server and returns just in time for the
    # shutdown. The init server is started with listen_addresses='' precisely so it is
    # invisible over TCP, so this cannot mistake it for the real thing.
    for _ in $(seq 1 120); do
        if docker exec {{ db_container }} pg_isready -h 127.0.0.1 -U agents -d agents >/dev/null 2>&1; then
            echo "postgres ready on :{{ db_port }}"
            exit 0
        fi
        sleep 0.5
    done

    echo "error: postgres did not become ready" >&2
    docker logs {{ db_container }} 2>&1 | tail -20 >&2
    exit 1

# Stop the local Postgres, keeping its data
db-down:
    -docker stop {{ db_container }}

# Delete the local Postgres and everything in it, then start a fresh one
db-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    docker rm -f {{ db_container }} >/dev/null 2>&1 || true

    # A volume that is not there is already in the state this recipe wants — that is the
    # normal case on a fresh clone, and treating it as an error made `just db-reset` fail
    # on any machine that had never run `just db-up`. A volume that exists and *cannot* be
    # removed is the real problem: db-up would then start against the old data and report
    # success, so a command whose whole job is to wipe the database silently would not.
    if docker volume inspect agents-pgdata >/dev/null 2>&1; then
        if ! docker volume rm agents-pgdata >/dev/null 2>&1; then
            echo "error: could not remove volume agents-pgdata — is another container using it?" >&2
            docker ps -a --filter volume=agents-pgdata --format '  still attached: {{{{.Names}}}} ({{{{.Status}}}})' >&2
            exit 1
        fi
    fi

    {{ just_executable() }} db-up

# Open a psql shell on the local database — or pipe SQL in: `echo 'select …' | just db-psql`
db-psql *args:
    #!/usr/bin/env bash
    set -euo pipefail
    # -t only when there is a terminal to attach: docker refuses it otherwise, which is
    # what would break piping SQL in. just flattens *args into one whitespace-split
    # string, so a quoted `-c "select …"` does not survive — pipe it instead.
    tty_flags=(-i)
    [ -t 0 ] && tty_flags+=(-t)
    exec docker exec "${tty_flags[@]}" {{ db_container }} psql -U agents -d agents {{ args }}

# Apply pending migrations to the local database
db-migrate: db-up
    uv run --project backend alembic -c backend/alembic.ini upgrade head

# Show the SQL a migration would run, without touching the database
db-migrate-sql:
    uv run --project backend alembic -c backend/alembic.ini upgrade head --sql

# Roll the local database back one revision
db-rollback: db-up
    uv run --project backend alembic -c backend/alembic.ini downgrade -1

# What the local database is at, and what exists
db-migration-status: db-up
    uv run --project backend alembic -c backend/alembic.ini current
    uv run --project backend alembic -c backend/alembic.ini history

# Create an empty revision to fill in by hand (there is no autogenerate — see migrations/README)
db-revision message: db-up
    uv run --project backend alembic -c backend/alembic.ini revision -m "{{ message }}"

# Forward a local port to Aurora through the instance over SSM (Ctrl-C to close)
db-tunnel local_port="15432":
    #!/usr/bin/env bash
    set -euo pipefail

    # Aurora sits in a private subnet with no route off the VPC, so the instance is the
    # only thing that can reach it. Session Manager forwards a port through that instance
    # without opening one on it — same trust path as `just ssh`, no inbound rule, no key.
    instance="$(terraform -chdir=infrastructure output -raw ec2_instance_id 2>/dev/null || true)"
    region="$(terraform -chdir=infrastructure output -raw aws_region 2>/dev/null || true)"
    endpoint="$(terraform -chdir=infrastructure output -raw db_cluster_endpoint 2>/dev/null || true)"
    if [ -z "$instance" ] || [ -z "$region" ] || [ -z "$endpoint" ]; then
        echo "error: missing terraform outputs — run 'terraform -chdir=infrastructure apply' first" >&2
        exit 1
    fi

    echo "forwarding 127.0.0.1:{{ local_port }} -> $endpoint:5432 via $instance"
    exec aws ssm start-session \
        --target "$instance" \
        --region "$region" \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters "host=$endpoint,portNumber=5432,localPortNumber={{ local_port }}"

# One-time: create the IAM-authenticated database role the deployed app connects as
db-bootstrap local_port="15433":
    #!/usr/bin/env bash
    set -euo pipefail

    # Run once after the first apply, and again only if db_app_username changes. The app
    # cannot create this role itself: it has no password anywhere, and a role that can
    # grant rds_iam is exactly what we are avoiding giving it.
    #
    # The master password is read here, on your machine, from the Secrets Manager secret
    # AWS generates and rotates. It is never given to the instance — the instance role
    # has no secretsmanager permission — so this is the one operation that needs your
    # own AWS credentials rather than the instance's.
    region="$(terraform -chdir=infrastructure output -raw aws_region)"
    endpoint="$(terraform -chdir=infrastructure output -raw db_cluster_endpoint)"
    database="$(terraform -chdir=infrastructure output -raw db_name)"
    master="$(terraform -chdir=infrastructure output -raw db_master_secret_arn)"
    app_user="$(terraform -chdir=infrastructure output -raw db_app_username)"
    migrator="$(terraform -chdir=infrastructure output -raw db_migrator_username)"
    instance="$(terraform -chdir=infrastructure output -raw ec2_instance_id)"

    password="$(aws secretsmanager get-secret-value --secret-id "$master" --region "$region" \
        --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')"
    username="$(aws secretsmanager get-secret-value --secret-id "$master" --region "$region" \
        --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])')"

    echo "opening a tunnel to $endpoint"
    aws ssm start-session \
        --target "$instance" \
        --region "$region" \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters "host=$endpoint,portNumber=5432,localPortNumber={{ local_port }}" \
        >/dev/null 2>&1 &
    tunnel=$!
    trap 'kill $tunnel 2>/dev/null || true' EXIT INT TERM

    for _ in $(seq 1 30); do
        nc -z 127.0.0.1 {{ local_port }} 2>/dev/null && break
        sleep 1
    done
    nc -z 127.0.0.1 {{ local_port }} 2>/dev/null || {
        echo "error: port forward to $endpoint never opened" >&2
        exit 1
    }

    # psql comes from the postgres image rather than the host, which already has to have
    # Docker for `just db-up`. sslmode=require, not verify-full: through the tunnel the
    # certificate names the Aurora endpoint, not localhost, so verification would fail
    # on a hostname mismatch that means nothing here.
    #
    # GRANT rds_iam is what makes the role token-authenticated; a role holding it cannot
    # log in with a password at all, which is the property being bought. The grants on
    # the schema give the migrator somewhere to create tables — Postgres 15 stopped
    # letting PUBLIC create in `public` — and leave the app with USAGE and no CREATE.
    docker run --rm -i \
        --add-host=host.docker.internal:host-gateway \
        -e PGPASSWORD="$password" \
        {{ postgres_image }} \
        psql -v ON_ERROR_STOP=1 \
            "host=host.docker.internal port={{ local_port }} dbname=$database user=$username sslmode=require" <<SQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$migrator') THEN
            CREATE ROLE $migrator WITH LOGIN;
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$app_user') THEN
            CREATE ROLE $app_user WITH LOGIN;
        END IF;
    END
    \$\$;

    -- Everything below this line acts on the migrator's behalf — handing it the schema,
    -- setting its default privileges, granting on tables it owns — and all of it requires
    -- membership in the role, not merely the right to have created it. Postgres 16+
    -- records the creation grant as ADMIN only, with SET and INHERIT both false: the
    -- master may hand out membership in the role without holding it. So ALTER SCHEMA
    -- ... OWNER TO is refused with "must be able to SET ROLE", and ALTER DEFAULT
    -- PRIVILEGES FOR ROLE with "permission denied to change default privileges". ADMIN is
    -- exactly enough to grant ourselves the membership those need, which is what this
    -- does; it is dropped again at the end of the script.
    GRANT $migrator TO $username;

    -- Both authenticate by token. A role holding rds_iam cannot log in with a password
    -- at all, which is the property being bought: there is no password to leak.
    GRANT rds_iam TO $migrator;
    GRANT rds_iam TO $app_user;

    GRANT CONNECT ON DATABASE $database TO $migrator;
    GRANT CONNECT ON DATABASE $database TO $app_user;

    -- The migrator owns the schema; it is the only role that may change it.
    ALTER SCHEMA public OWNER TO $migrator;
    GRANT USAGE, CREATE ON SCHEMA public TO $migrator;

    -- The app may read and write rows and nothing else. Deliberately no CREATE: a bug
    -- or an injection in the running app cannot reach the schema.
    GRANT USAGE ON SCHEMA public TO $app_user;
    REVOKE CREATE ON SCHEMA public FROM $app_user;

    -- Tables the migrator creates are owned by the migrator, so the app would have no
    -- rights on them without this. Covers future migrations; the GRANTs below cover
    -- anything that already exists.
    ALTER DEFAULT PRIVILEGES FOR ROLE $migrator IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $app_user;
    ALTER DEFAULT PRIVILEGES FOR ROLE $migrator IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO $app_user;

    -- Still inside the membership, because these tables are owned by the migrator. On a
    -- first run the schema is empty and this is a no-op; it matters on a re-run after
    -- db_app_username changes, which is the case the catch-up exists for.
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $app_user;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO $app_user;

    -- The membership was only needed to issue the statements above; what they wrote —
    -- pg_default_acl entries and table grants — outlives it. Dropping it again leaves the
    -- master able to administer the cluster but not to act as the schema owner, which is
    -- the separation the two roles exist for.
    REVOKE $migrator FROM $username;
    SQL

    echo "'$migrator' owns the schema; '$app_user' has DML only. Both sign in with IAM tokens."
    echo "next: 'just deploy' — agents-migrate.service applies migrations before the app starts"

# Build the frontend into backend/static, where the app serves it from
build: frontend-build
    rm -rf backend/static
    cp -R frontend/out backend/static

# Serve the built frontend and API from one origin at http://localhost:8000, as production does
serve: build db-up db-migrate
    uv run --project backend uvicorn main:app --app-dir backend --port 8000

# Build the production image (frontend export + API in one container)
docker-build:
    docker build -f backend/Dockerfile -t agents:local .

# Smoke-test an already-built image against a throwaway Postgres (CI passes the tag it just built)
smoke image="agents:local" port="8080":
    #!/usr/bin/env bash
    set -euo pipefail
    name="agents-smoke-{{ port }}"
    db="$name-db"
    network="$name-net"

    # A Postgres of its own rather than the `just db-up` one: this has to pass on a
    # machine that has never run the dev database, it must not touch real data, and
    # every run has to start from an empty schema so the app's own migration is what
    # creates it. Named per-port so two smoke runs can overlap.
    docker rm -f "$name" "$db" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true

    cleanup() {
        rc=$?
        if [ "$rc" -ne 0 ]; then
            echo "--- app logs ---" >&2
            docker logs "$name" 2>&1 | tail -40 >&2 || true
            echo "--- postgres logs ---" >&2
            docker logs "$db" 2>&1 | tail -20 >&2 || true
        fi
        docker rm -f "$name" "$db" >/dev/null 2>&1 || true
        docker network rm "$network" >/dev/null 2>&1 || true
        exit "$rc"
    }
    trap cleanup EXIT

    # A user-defined network gives the containers DNS, so the app can reach the database
    # by container name. Postgres itself is not published to the host — nothing outside
    # this network needs it.
    docker network create "$network" >/dev/null
    docker run -d --name "$db" --network "$network" \
        -e POSTGRES_USER=agents \
        -e POSTGRES_PASSWORD=agents \
        -e POSTGRES_DB=agents \
        {{ postgres_image }} >/dev/null

    # -h 127.0.0.1 to check over TCP rather than the socket. The entrypoint's temporary
    # init server listens on the socket only, so a socket check reports ready during
    # initdb and then the server shuts down to restart for real — which is exactly the
    # race that failed in CI, where the image was pulled cold. See `db-up` above.
    for _ in $(seq 1 120); do
        docker exec "$db" pg_isready -h 127.0.0.1 -U agents -d agents >/dev/null 2>&1 && break
        sleep 0.5
    done
    docker exec "$db" pg_isready -h 127.0.0.1 -U agents -d agents >/dev/null 2>&1 || {
        echo "error: smoke-test postgres did not become ready" >&2
        exit 1
    }

    # Migrate from the image before starting it, which is what agents-migrate.service
    # does on the box. This is the only place the image's migration path is exercised:
    # the app no longer creates its own schema, so without this the container would come
    # up against an empty database and every pantry query would fail.
    docker run --rm --network "$network" \
        -e DATABASE_URL="postgresql://agents:agents@$db:5432/agents" \
        --entrypoint /app/.venv/bin/alembic \
        {{ image }} -c /app/alembic.ini upgrade head

    docker run -d --name "$name" --network "$network" -p {{ port }}:8080 \
        -e GOOGLE_CLIENT_ID=smoke-test \
        -e GOOGLE_CLIENT_SECRET=smoke-test \
        -e ALLOWED_EMAILS=smoke@example.com \
        -e DATABASE_URL="postgresql://agents:agents@$db:5432/agents" \
        {{ image }} >/dev/null
    python3 scripts/smoke_test.py "http://127.0.0.1:{{ port }}"

# Build the production image and smoke-test it
docker-check: docker-build smoke

# Run the production image at http://localhost:8080, against the local Postgres
docker-run: docker-build db-up db-migrate
    # DATABASE_URL is set here rather than passed through from .env, whose value points
    # at 127.0.0.1 — which inside the container is the container. host.docker.internal
    # is what reaches the daemon's host, and --add-host provides it on Linux, where it
    # is not built in as it is on Docker Desktop.
    docker run --rm -p 8080:8080 \
        --add-host=host.docker.internal:host-gateway \
        -e ANTHROPIC_API_KEY \
        -e GOOGLE_CLIENT_ID \
        -e GOOGLE_CLIENT_SECRET \
        -e SESSION_SECRET \
        -e ALLOWED_EMAILS \
        -e ALLOWED_SERVICE_ACCOUNTS \
        -e APP_BASE_URL="${APP_BASE_URL:-http://localhost:8080}" \
        -e DATABASE_URL="postgresql://agents:agents@host.docker.internal:{{ db_port }}/agents" \
        agents:local

# Remove build output
clean:
    rm -rf backend/static frontend/out frontend/.next

# ── Infrastructure ─────────────────────────────────────────────────────────────

# Open a shell on the deployed instance over SSM (no SSH key, no inbound port)
ssh *args:
    #!/usr/bin/env bash
    set -euo pipefail

    # just runs recipes from the justfile's directory, so this works from anywhere
    # in the repo and -chdir always resolves to the one terraform config.
    instance="$(terraform -chdir=infrastructure output -raw ec2_instance_id 2>/dev/null || true)"
    if [ -z "$instance" ]; then
        echo "error: no ec2_instance_id output from infrastructure/" >&2
        echo "       run 'terraform -chdir=infrastructure init' and apply first" >&2
        exit 1
    fi

    exec aws ssm start-session --target "$instance" {{ args }}

# Restart the app so it re-reads its image tag and config from Parameter Store
restart:
    #!/usr/bin/env bash
    set -euo pipefail

    instance="$(terraform -chdir=infrastructure output -raw ec2_instance_id 2>/dev/null || true)"
    region="$(terraform -chdir=infrastructure output -raw aws_region 2>/dev/null || true)"
    if [ -z "$instance" ] || [ -z "$region" ]; then
        echo "error: no ec2_instance_id/aws_region output from infrastructure/" >&2
        echo "       run 'terraform -chdir=infrastructure init' and apply first" >&2
        exit 1
    fi

    # The unit fetches every value on start, so a plain restart is the whole rollout.
    echo "restarting agents.service on $instance"
    command_id="$(aws ssm send-command \
        --instance-ids "$instance" \
        --region "$region" \
        --document-name AWS-RunShellScript \
        --comment "roll out app version/config from Parameter Store" \
        --parameters 'commands=["systemctl restart agents.service"]' \
        --query Command.CommandId --output text)"

    # Poll until the command reaches a terminal status. `systemctl restart` blocks
    # while ExecStartPre pulls the image, which can legitimately exceed the SSM
    # waiter's default ~100s timeout.
    status="InProgress"
    while [ "$status" = "InProgress" ] || [ "$status" = "Pending" ] || [ "$status" = "Delayed" ]; do
        sleep 5
        status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" --region "$region" --query Status --output text)"
    done
    if [ "$status" != "Success" ]; then
        echo "error: restart command finished as '$status'" >&2
        aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" --region "$region" \
            --query 'StandardErrorContent' --output text >&2
        exit 1
    fi

    # Checked from here rather than on the box, so a pass proves the whole path a user
    # takes — tailnet, `tailscale serve`, then the app — not just that systemd is happy.
    url="$(terraform -chdir=infrastructure output -raw app_url)"
    echo "waiting for $url/health"
    for _ in $(seq 1 60); do
        if curl -fsS --max-time 5 "$url/health" >/dev/null 2>&1; then
            echo "healthy"
            exit 0
        fi
        sleep 2
    done
    echo "error: $url/health did not respond after the restart" >&2
    echo "       check 'just ssh' → journalctl -u agents.service" >&2
    exit 1

# Apply infrastructure changes, then roll them out without replacing the instance
deploy *args:
    terraform -chdir=infrastructure apply {{ args }}
    {{ just_executable() }} restart

# ── Backend ────────────────────────────────────────────────────────────────────

# Install backend dependencies
backend-install:
    sfw uv sync --dev --project backend

# Start backend dev server on :8000 (also serves backend/static if `just build` ran)
#
# Migrates first, like every other recipe that starts the app: the schema belongs to
# Alembic now, so a backend started against an unmigrated database comes up healthy and
# then 500s on the first pantry query.
backend-dev: db-up db-migrate
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
    sfw pnpm --dir frontend install --frozen-lockfile

# Start frontend dev server on :3000, proxying /api to the backend on :8000
frontend-dev:
    pnpm --dir frontend run dev

# Run frontend linter
frontend-lint:
    pnpm --dir frontend run lint

# Build frontend (type check + compile)
frontend-build:
    pnpm --dir frontend run build

# Run frontend tests
frontend-test:
    pnpm --dir frontend run test

# Run all frontend checks
frontend-check: frontend-lint frontend-build frontend-test

# ── CLI (Safari history export) ────────────────────────────────────────────────

# Where the dedicated virtualenv lives. It is dedicated, rather than shared or run
# through uvx, because Full Disk Access is granted to the interpreter behind the
# console script — see cli/README.md. Anything else would extend that grant to every
# script the same interpreter runs.
cli_home := join(env('HOME'), "Library/Application Support/safari-history-export")
cli_venv := join(cli_home, "venv")
cli_bin := join(cli_venv, "bin/export-safari-history")
cli_label := "com.ryandens.safari-history-export"
cli_plist := join(env('HOME'), "Library/LaunchAgents", cli_label + ".plist")

# Install the exporter into its own virtualenv, then print the path to grant FDA to
cli-install:
    #!/usr/bin/env bash
    set -euo pipefail

    # Built by an interpreter matching cli/.python-version rather than by whatever
    # `python3` happens to be on PATH. Without this the venv silently takes the system
    # version, and the install fails several steps later on requires-python with a
    # message that never mentions the pin.
    version="$(cat cli/.python-version)"
    if ! interpreter="$(uv python find "$version" 2>/dev/null)"; then
        echo "error: no Python $version found — install one with 'uv python install $version'" >&2
        exit 1
    fi

    # --copies gives the virtualenv its own copy of the python binary at a stable path
    # nothing else uses. A symlinked venv would point Full Disk Access back at the
    # shared interpreter it was created from, which is the thing this avoids.
    "$interpreter" -m venv --copies "{{ cli_venv }}"
    sfw "{{ cli_venv }}/bin/pip" install --quiet --upgrade pip
    sfw "{{ cli_venv }}/bin/pip" install --quiet --upgrade ./cli

    # The virtualenv holds a Full Disk Access grant; anything that can write into it
    # can run code under that grant.
    chmod -R go-rwx "{{ cli_home }}"

    echo
    echo "installed: {{ cli_bin }}"
    echo
    "{{ cli_bin }}" status || true
    echo
    echo "Grant Full Disk Access to the interpreter printed above:"
    echo "  System Settings → Privacy & Security → Full Disk Access → + (⌘⇧G to paste)"

# Show configuration, permissions, and pending work
cli-status:
    "{{ cli_bin }}" status

# Export and upload; pass a date to do one specific day (e.g. `just cli-run 2026-07-29`)
cli-run *args:
    "{{ cli_bin }}" {{ args }}

# Render the LaunchAgent plist with absolute paths and load it
cli-install-agent:
    #!/usr/bin/env bash
    set -euo pipefail

    if [ ! -x "{{ cli_bin }}" ]; then
        echo "error: {{ cli_bin }} is not installed — run 'just cli-install' first" >&2
        exit 1
    fi

    api_url="${SAFARI_HISTORY_API_URL:-}"
    credentials="${GOOGLE_APPLICATION_CREDENTIALS:-}"
    for name in api_url credentials; do
        if [ -z "${!name}" ]; then
            echo "error: set SAFARI_HISTORY_API_URL and GOOGLE_APPLICATION_CREDENTIALS" >&2
            echo "       (in .env, which just loads, or in the environment)" >&2
            exit 1
        fi
    done

    mkdir -p "$HOME/Library/LaunchAgents"
    # launchd never expands ~ or reads a shell profile, so every path in the plist has
    # to be absolute before it is written.
    #
    # Rendered by safari_history.launch_agent rather than sed: sed reads `&` in a
    # replacement as "the text that matched", so an API URL with a query string would
    # write the __API_URL__ placeholder back into the plist instead of the URL. See that
    # module for the rest of the reasoning.
    rendered="$(mktemp)"
    trap 'rm -f "$rendered"' EXIT
    AGENT_HOME="$HOME" AGENT_API_URL="$api_url" AGENT_CREDENTIALS="$credentials" \
        "{{ cli_venv }}/bin/python" -m safari_history.launch_agent \
        cli/launchd/{{ cli_label }}.plist > "$rendered"

    # Catches a malformed plist here, with a line number, rather than as launchctl's
    # much vaguer "Bootstrap failed: 5: Input/output error".
    plutil -lint "$rendered" >/dev/null
    mv "$rendered" "{{ cli_plist }}"
    trap - EXIT

    # bootout first so re-running this picks up an edited plist; ignore "not loaded".
    launchctl bootout "gui/$(id -u)/{{ cli_label }}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "{{ cli_plist }}"

    echo "loaded {{ cli_label }} — runs daily at 00:15"
    echo "  just cli-agent-run     run it now"
    echo "  just cli-logs          watch the log"

# Run the LaunchAgent job now, the way launchd would
cli-agent-run:
    launchctl kickstart -p "gui/$(id -u)/{{ cli_label }}"

# Show the LaunchAgent's state and last exit code
cli-agent-status:
    launchctl print "gui/$(id -u)/{{ cli_label }}"

# Follow the exporter's logs
cli-logs:
    tail -f "$HOME/Library/Logs/safari-history-export.log" \
            "$HOME/Library/Logs/safari-history-export.error.log"

# Unload the LaunchAgent, leaving the install in place
cli-uninstall-agent:
    #!/usr/bin/env bash
    set -euo pipefail
    launchctl bootout "gui/$(id -u)/{{ cli_label }}" 2>/dev/null || true
    rm -f "{{ cli_plist }}"
    echo "unloaded {{ cli_label }}"

# Remove the LaunchAgent, the virtualenv, and the state (exported CSVs are kept)
cli-uninstall: cli-uninstall-agent
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf "{{ cli_home }}"
    rm -f "$HOME/Library/Logs/safari-history-export.log" \
          "$HOME/Library/Logs/safari-history-export.error.log"
    echo "removed {{ cli_home }}"
    echo
    echo "Still to do by hand:"
    echo "  - remove the Full Disk Access entry (System Settings → Privacy & Security)"
    echo "  - delete ~/Safari-History-Exports if you no longer want the CSVs"

# Install cli development dependencies
cli-dev-install:
    sfw uv sync --dev --project cli

# Run cli linter
cli-lint:
    uv run --project cli ruff check cli

# Run cli format check
cli-fmt:
    uv run --project cli ruff format --check cli

# Run cli tests
cli-test:
    uv run --project cli pytest cli

# Run all cli checks
cli-check: cli-lint cli-fmt cli-test

# ── CI ─────────────────────────────────────────────────────────────────────────

# Run all checks (mirrors CI)
check: backend-check frontend-check cli-check
