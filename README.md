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

# Create .env at the repo root
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

## Running

```sh
just dev
```

Opens the frontend at `http://localhost:3000` and the backend at `http://localhost:8000`.

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

The app runs on AWS at [agents.ryandens.com](https://agents.ryandens.com), behind a Google OIDC-gated ALB. Infrastructure is managed with Terraform in `infrastructure/`.

### Releasing a new version

Releasing builds the Docker image, pushes it to ECR, and builds the frontend static export as a GitHub Actions artifact — it does **not** deploy anything.

```sh
gh release create 0.2.0 --title "0.2.0" --notes "..."
```

This pushes the `0.2.0` tag, triggering the GitHub Actions release workflow. Two jobs run in parallel:

- **docker** — builds a multi-arch image and pushes to ECR
- **frontend** — runs `next build` and uploads `frontend/out/` as a versioned artifact

Wait for both to go green before deploying.

### Deploying a new version

Deploy the backend (EC2) and frontend (S3/CloudFront) together so they stay in sync.

#### Backend

Terraform upgrades by replacing the EC2 instance with a new one that runs `user_data` on boot. The new instance pulls the target image, starts the systemd service, and passes ALB health checks before traffic switches over. **Pantry data stored in `/opt/agents/data` is lost on replacement** until that path is moved to a separate EBS volume or EFS.

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

Terraform will show `aws_instance.app must be replaced`. Confirm. The old instance is terminated, the new one starts, and once health checks pass (~2 min) the ALB routes traffic to it.

#### Frontend

**Step 1 — download the artifact** from the GitHub Actions run for the release tag:

```sh
gh run download --name frontend-0.2.0 --dir /tmp/frontend-out
```

**Step 2 — sync to S3** (two passes to set correct cache headers):

```sh
# HTML and root files — no cache
aws s3 sync /tmp/frontend-out/ s3://$(terraform -chdir=infrastructure output -raw s3_frontend_bucket)/ \
  --exclude "_next/static/*" \
  --cache-control "public,max-age=0,must-revalidate" \
  --delete

# Hashed static assets — cache forever
aws s3 sync /tmp/frontend-out/_next/static/ s3://$(terraform -chdir=infrastructure output -raw s3_frontend_bucket)/_next/static/ \
  --cache-control "public,max-age=31536000,immutable"
```

**Step 3 — invalidate CloudFront**

```sh
aws cloudfront create-invalidation \
  --distribution-id $(terraform -chdir=infrastructure output -raw cloudfront_distribution_id) \
  --paths "/*"
```

## Development

```sh
just dev            # start both servers with hot-reload
just check          # run all checks (mirrors CI)

just backend-test   # pytest
just backend-lint   # ruff check
just backend-fmt    # ruff format --check

just frontend-test  # vitest
just frontend-lint  # eslint
just frontend-build # next build (type-check + compile)
```
