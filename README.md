# Ryan's Agents

A collection of AI agents. Currently home to one: the **Kitchen Agent**.

## Agents

### Kitchen Agent

An AI-powered meal planning and kitchen management app. Chat with the agent to plan meals, find recipes, and build grocery lists — then track what you actually have with the pantry manager.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.14, FastAPI, Anthropic SDK (`claude-opus-4-7`) |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS v4, Vercel AI SDK v6 |
| Package managers | `uv` (backend), `npm` (frontend) |
| Task runner | `just` |

## Prerequisites

- [just](https://github.com/casey/just)
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 (use `nvm` — `.nvmrc` is included)
- An Anthropic API key

## Setup

```sh
# Install dependencies
just backend-install
just frontend-install

# Write .env at the repo root from 1Password
just env-sync
```

`just env-sync` reads the `agents.ryandens.com` item for the Google OAuth `client_id`,
`client_secret`, and (optionally) `allowed_emails`, and the `Claude API Key` item for
the Anthropic key (override with `OP_OAUTH_ITEM` / `OP_API_KEY_ITEM`). It generates a
`SESSION_SECRET` on first run and preserves it afterwards, so re-running does not sign
you out. Without 1Password, write the file by hand instead:

```sh
# Generate a random session secret
SESSION_SECRET=$(openssl rand -base64 32)

# Write .env file
cat > .env <<EOF
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
APP_BASE_URL=http://localhost:3000
SESSION_SECRET=$SESSION_SECRET
ALLOWED_EMAILS=you@example.com
EOF
```

### How sign-in works

The backend runs the OIDC **authorization code flow with PKCE** as a confidential
client. `/api/auth/login` redirects to Google; Google redirects back to
`/api/auth/callback` with a one-time code; the backend exchanges that code for an ID
token over its own TLS connection to Google using `GOOGLE_CLIENT_SECRET`, verifies the
token (signature, issuer, audience, expiry, and the `nonce` it issued), then drops it
and issues a signed HttpOnly session cookie. No Google token ever reaches the browser,
and the frontend bundle contains no client ID.

For this to work, the OAuth client needs `$APP_BASE_URL/api/auth/callback` registered as
an **authorized redirect URI** — `http://localhost:3000/api/auth/callback` for dev and
`https://agents.<your-tailnet>.ts.net/api/auth/callback` for production, matching the
`app_url` Terraform output. (The old setup needed an authorized *JavaScript origin*
instead; that is no longer used.)

### Who can sign in

`ALLOWED_EMAILS` — a comma-separated list — is the **only** thing restricting access.
An empty value rejects everyone.

This carries the weight because Google will not do it. An app that requests only
`openid`, `email`, and `profile` is [explicitly exempt][audience] from the OAuth consent
screen's Testing-mode restrictions: test users are not required, no unverified-app
warning appears, and consent does not expire after 7 days. So adding or removing people
from the test-user list in the Google Cloud console changes nothing. Restricting by
Google Workspace org (`Internal` user type) is not an option either, since this is an
External client on a personal account.

[audience]: https://support.google.com/cloud/answer/15549945

## Running

```sh
just dev
```

Open `http://localhost:3000`. The frontend dev server runs there with hot-reload and
proxies `/api/*` to the backend on `http://localhost:8000`, which runs with
`uvicorn --reload`. Both halves reload on save, and the app sees a single origin — the
same shape as production.

To run it exactly as production does, with the static export served by the backend:

```sh
just serve         # builds the frontend into backend/static, serves both on :8000
just docker-run    # or the same thing in the production image, on :8080
```

Both listen on a different port than `just dev`, so sign-in needs a matching
`APP_BASE_URL` — otherwise Google bounces the callback back to `:3000`:

```sh
APP_BASE_URL=http://localhost:8080 just env-sync
```

That value sticks in `.env` for later runs, and `env-sync` prints the redirect URI to
register for whichever base URL is in effect.

## Features

### Chat (`/`)

Conversational interface powered by `claude-opus-4-7`. Ask it to plan meals, suggest recipes, or build a grocery list. Streams responses via Server-Sent Events.

### Pantry (`/pantry`)

Track everything in your kitchen:

- **Three storage locations** — Pantry, Fridge, Freezer
- **Rich item data** — name, brand, category, quantity, unit, purchase date, expiration date, notes
- **14 categories** — Produce, Dairy, Meat, Seafood, Grains, Legumes, Condiments, Spices, Beverages, Snacks, Baking, Canned, Frozen, Other
- **20 units** — weight, volume, count, and container types
- **Expiry badges** — green (fresh), amber (≤ 3 days), red (expired)
- **Category filter pills** — narrow the view without leaving the tab
- Items sorted by expiration date, soonest first

Data is stored in `backend/data/pantry.json`. The storage layer is designed to be swapped for a relational database or DynamoDB without changing the API.

## Deployment

The app runs on AWS and is reachable **only over Tailscale**, at
`https://agents.<your-tailnet>.ts.net` (the exact URL is the `app_url` Terraform output).
There is no load balancer, no public DNS record, and no port open to the internet — the
EC2 security group allows one inbound rule, Tailscale's own WireGuard port. Off the
tailnet the instance simply does not answer.

On the instance, `tailscale serve` terminates TLS with a Tailscale-issued certificate for
the node's MagicDNS name and proxies to the app on `127.0.0.1:8080`. The container
publishes that port on loopback only, so `tailscale serve` is the sole way in. One
container serves both halves of the app: the frontend's static export at `/`, and the API
under `/api/...`. Same origin, so there is no CORS and no CDN to invalidate.
Infrastructure is managed with Terraform in `infrastructure/`.

### Tailnet prerequisites

Before the first apply, in the [Tailscale admin console](https://login.tailscale.com/admin):

1. **Enable HTTPS certificates** (DNS → HTTPS Certificates). Without this `tailscale
   serve --https=443` fails and the instance comes up with nothing listening.
2. **Generate a reusable, pre-approved auth key** (Settings → Keys) and set it as
   `tailscale_auth_key` in `terraform.tfvars`. It must be reusable rather than ephemeral:
   an ephemeral node is reaped whenever it goes offline, so the instance would lose its
   identity across a reboot. Auth keys expire after 90 days at most — rotate the value
   before the instance is next replaced, or the replacement will fail to join.
3. Note the tailnet's DNS name (DNS page, e.g. `tail1a2b3c.ts.net`) and set it as
   `tailscale_tailnet`. Together with `tailscale_hostname` it composes the app's only
   origin — the `app_url` output, and the `APP_BASE_URL` the instance runs with.

Sign-in redirects back to that origin, so add
`https://agents.<your-tailnet>.ts.net/api/auth/callback` to the OAuth client's authorized
redirect URIs alongside `http://localhost:3000/api/auth/callback`.

### Releasing a new version

Releasing builds the Docker image and pushes it to ECR — it does **not** deploy anything.

```sh
gh release create 0.2.0 --title "0.2.0" --notes "..."
```

This pushes the `0.2.0` tag, triggering the GitHub Actions release workflow. The image is
built from the repository root (`-f backend/Dockerfile .`) so a Node stage can run
`next build` and copy `frontend/out` into the image at `/app/static`. The frontend and the
API therefore ship as one versioned artifact and cannot drift apart.

Wait for the workflow to go green before deploying.

### Deploying a new version

Terraform upgrades by replacing the EC2 instance with a new one that runs `user_data` on boot. The new instance pulls the target image, starts the systemd service, joins the tailnet, and waits for `/health` to answer before finishing boot. There is no load balancer to drain, so **the app is down for the couple of minutes between the old instance shutting down and the new one joining the tailnet.** **Pantry data stored in `/opt/agents/data` is lost on replacement** until that path is moved to a separate EBS volume or EFS.

**Step 1 — get the new image digest**

```sh
crane digest 749549498353.dkr.ecr.us-east-1.amazonaws.com/agents:0.2.0
```

**Step 2 — update `infrastructure/terraform.tfvars`**

```hcl
app_version = "0.2.0@sha256:<digest from step 1>"
```

**Step 3 — apply**

```sh
terraform -chdir=infrastructure apply
```

Terraform will show `aws_instance.app must be replaced`. Confirm. The old instance is terminated — leaving the tailnet as it shuts down, so the replacement can reclaim the `agents` MagicDNS name rather than being renamed `agents-1` — and the new one takes its place after ~2 min. There is no load balancer to drain, so the app is unreachable in between. The frontend ships inside that image, so there is no separate frontend deploy.

Auth-related variables live alongside `app_version` in `terraform.tfvars` — see
`terraform.tfvars.example`. `google_client_secret` and a generated session key are stored
as SSM `SecureString` parameters and fetched by the systemd unit at start, rather than
being rendered into EC2 user data where anything on the box could read them.
`allowed_emails` sets who may sign in; changing it takes effect on the next instance
replacement. There is no `app_base_url` variable: the app has exactly one origin now, so
it is derived from `tailscale_hostname` and `tailscale_tailnet` and surfaced as the
`app_url` output.

If the URL ever resolves to `agents-1.<tailnet>.ts.net`, a retired node is still holding
the name; remove it from the admin console's machine list.

## Development

```sh
just dev            # start both servers with hot-reload
just serve          # build the frontend and serve everything from :8000, like production
just docker-run     # build and run the production image on :8080
just docker-check   # build the production image and smoke-test it (mirrors the CI docker job)
just check          # run all checks (mirrors CI)

just backend-test   # pytest
just backend-lint   # ruff check
just backend-fmt    # ruff format --check

just frontend-test  # vitest
just frontend-lint  # eslint
just frontend-build # next build (type-check + compile)
```

`scripts/smoke_test.py` checks a running container end to end: that `/` serves the React
app, `/api/*` still reaches FastAPI rather than the static mount, `/pantry` redirects to
`/pantry/`, and the Google client ID reached the browser bundle. It is stdlib-only, so CI
runs it without installing anything. Point it at any deployment:

```sh
python3 scripts/smoke_test.py "$(terraform -chdir=infrastructure output -raw app_url)"
```
