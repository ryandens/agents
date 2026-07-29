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

`just env-sync` reads the `agents.ryandens.com` item for the Google OAuth client ID and
the `Claude API Key` item for the Anthropic key (override with `OP_OAUTH_ITEM` /
`OP_API_KEY_ITEM`). Without 1Password, write the file by hand instead:

```sh
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
EOF
```

`GOOGLE_CLIENT_ID` is what the backend verifies ID tokens against; `just dev` and
`just build` mirror it into `NEXT_PUBLIC_GOOGLE_CLIENT_ID` so the browser's sign-in
button gets the same value. Sign-in also requires `http://localhost:3000` to be an
authorized JavaScript origin on that OAuth client.

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
   `tailscale_tailnet`. It only composes the `app_url` output.

Google sign-in checks the origin, so add `https://agents.<your-tailnet>.ts.net` to the
OAuth client's authorized JavaScript origins alongside `http://localhost:3000`.

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

Terraform will show `aws_instance.app must be replaced`. Confirm. The old instance is terminated — leaving the tailnet as it shuts down, so the replacement can reclaim the `agents` MagicDNS name rather than being renamed `agents-1` — and the new one takes its place after ~2 min. The frontend ships inside that image, so there is no separate frontend deploy.

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
