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
| Database | PostgreSQL 17 — Aurora Serverless v2 in production, a container locally |
| Database auth | RDS IAM tokens in production (no stored password); password locally |
| Package managers | `uv` (backend), `npm` (frontend) |
| Task runner | `just` |

## Prerequisites

- [just](https://github.com/casey/just)
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 (use `nvm` — `.nvmrc` is included)
- Docker — runs the local Postgres, and the one the tests start
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
you out.

It also writes `infrastructure/terraform.tfvars`, which needs two values `.env` has no
use for: `tailscale_auth_key` and `tailscale_tailnet`. Those come from the same 1Password
item — any field labelled `tailscale_auth_key` / `auth_key` / `authkey` for the key, and
`tailscale_tailnet` / `tailnet` / `tailnet_name` for the tailnet, in a section or not.
Add `tailscale_hostname` too if the node should not be called `agents`. Anything it
cannot find is carried over from the previous `terraform.tfvars` and otherwise written as
a commented-out line, so a rename never silently blanks a working config.

Without 1Password, write the file by hand instead:

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

### Machine access

A script or service account has no browser, so it can never complete the redirect flow
above and never gets a session cookie. `ALLOWED_SERVICE_ACCOUNTS` — also comma-separated,
and **empty by default** — opens a second door for those callers: a Google-signed ID
token presented as `Authorization: Bearer <token>`.

The token must be minted for this app's origin as its audience. That audience check is
what keeps a token issued for some other service from being replayed here:

```python
from google.auth.transport.requests import Request
from google.oauth2 import service_account

creds = service_account.IDTokenCredentials.from_service_account_file(
    "key.json", target_audience="https://agents.<your-tailnet>.ts.net"
)
creds.refresh(Request())
print(creds.token)   # send as: Authorization: Bearer <token>
```

The two lists are kept separate on purpose. `ALLOWED_EMAILS` decides who may *sign in*;
`ALLOWED_SERVICE_ACCOUNTS` decides who may *call the API without signing in*. Putting a
service account in `ALLOWED_EMAILS` grants it nothing, since it will never reach the
callback that consults that list — and adding a colleague to `ALLOWED_EMAILS` does not
quietly mint them a machine credential.

Set it in `.env` for local runs and in `allowed_service_accounts` (a list) for
Terraform. `just env-sync` does not read it from 1Password; it carries whatever is
already in `.env` through to both files, so a hand-set value survives a re-run.

## Running

```sh
just dev
```

Open `http://localhost:3000`. The frontend dev server runs there with hot-reload and
proxies `/api/*` to the backend on `http://localhost:8000`, which runs with
`uvicorn --reload`. Both halves reload on save, and the app sees a single origin — the
same shape as production.

`just dev` also starts the Postgres the backend stores the pantry in, as a container on
`:5432`, and waits for it to accept connections before the servers come up. The backend
creates its schema on startup, so there is no migration step to remember. The data lives
in a Docker volume and outlives the container:

```sh
just db-up      # start it on its own (`just dev` does this for you)
just db-down    # stop it, keeping the data
just db-reset   # throw the database away and start a clean one
just db-psql    # psql shell — or pipe SQL in: echo 'select * from pantry_items;' | just db-psql
```

`DATABASE_URL` in `.env` selects the database; unset, the backend falls back to the same
local container, so nothing has to be configured to get started.

The container publishes Postgres on `127.0.0.1` only. If you have an `agents-postgres`
container from before that change, it kept the port binding it was created with — which
was every interface, with the password `agents` — because `docker start` cannot rebind a
port. Run `just db-reset` once to recreate it, or check with `docker port
agents-postgres` that it says `127.0.0.1:5432` rather than `0.0.0.0:5432`.

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

Items live in a single `pantry_items` table in Postgres — Aurora Serverless v2 in
production, a container in development and in tests. `backend/db.py` owns the pool and
creates the schema at startup; `backend/pantry_store.py` is the only module that writes
SQL, so the API layer is unchanged from when this was a file on disk.

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

### The database

The pantry lives in an Aurora PostgreSQL Serverless v2 cluster named `agents`, defined in
`infrastructure/rds.tf`. It sits in private subnets whose route table has no routes at
all — no internet gateway, no NAT — so there is no path to it from outside the VPC, and
its security group accepts port 5432 from exactly one source: the app instance's own
security group. Nothing else in the account can open a connection, and neither can a
laptop. To get a psql prompt, go through the instance with `just ssh`.

The instance's permission to read and write is two things together, and it needs both:

- **Network** — the ingress rule in `infrastructure/security_groups.tf`, which references
  the EC2 security group rather than a CIDR, so it keeps working when the instance is
  replaced and comes back on a different address.
- **Identity** — there is no database password for the app. It authenticates with an
  **RDS IAM token**: a 15-minute credential the app signs itself, at connect time, from
  the instance profile's credentials. The IAM policy in `infrastructure/rds.tf` allows
  `rds-db:connect` for one database user on one cluster, so revoking the app's access is
  deleting that statement.

That means nothing has to be rotated and there is no credential at rest anywhere — not
in Parameter Store, not in the image, not in Terraform state. `/agents/database-url` is a
plain `String` parameter holding a DSN with no password in it; it is no more sensitive
than a hostname.

The master user still exists for administration, but the app never uses it and neither
do you, day to day. Its password is created and **rotated by AWS** in Secrets Manager
(`manage_master_user_password`), so it never passes through Terraform — it is absent from
the plan and from state — and the instance role has no permission to read it.

Two consequences worth knowing:

- The instance's IMDS hop limit is **2**, not the usual 1, because the app runs in a
  container and Docker's bridge adds a hop. At 1 the container silently cannot read
  instance credentials and every database connection fails. The trade-off is that any
  container on that host could reach IMDS, which is fine on a box running one workload.
- A role granted `rds_iam` cannot log in with a password at all. That is the property
  being bought, and it is why the app's role is separate from the master.

Connect to it yourself over an SSM port forward through the instance — no inbound port,
no key, same trust path as `just ssh`:

```sh
just db-tunnel      # 127.0.0.1:15432 -> Aurora, until you Ctrl-C
```

The cluster scales to **zero** ACUs after an hour idle, which is what makes it affordable
for a household-sized app. The cost is that the first connection after a quiet stretch
waits roughly fifteen seconds for the cluster to resume — `db.py` opens its pool with a
60-second timeout for exactly this reason. Set `db_min_capacity = 0.5` to keep it warm
instead. Backups are retained for 7 days, storage is encrypted, and deletion protection is
on, so a `terraform destroy` fails rather than quietly taking the pantry with it.

`/health` now reports the database, not just the process, so a container that starts
without being able to reach Aurora fails the boot gate in `user_data.sh` and the rollout
gate in `just restart` instead of serving a broken pantry.

### Tailnet prerequisites

Before the first apply, in the [Tailscale admin console](https://login.tailscale.com/admin):

1. **Enable HTTPS certificates** (DNS → HTTPS Certificates). Without this `tailscale
   serve --https=443` fails and the instance comes up with nothing listening.
2. **Generate a reusable, ephemeral, pre-approved auth key** (Settings → Keys) and set it
   as `tailscale_auth_key` in `terraform.tfvars`. All three matter: *reusable* because
   every boot registers afresh, *pre-approved* so the node needs no manual click to become
   reachable, and *ephemeral* because only an ephemeral node can delete itself on shutdown
   and hand the `agents` machine name to its replacement. The instance keeps no durable
   tailnet identity, so an expired key breaks the next **boot**, not just the next
   replacement — auth keys last 90 days at most, so rotate before then.
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

Deploying does **not** replace the EC2 instance. The image tag and every config value live
in SSM Parameter Store; the systemd unit reads them on start, so a release is an in-place
parameter update followed by a restart of `agents.service`. The app is down only for the
few seconds the container takes to come back, and the pantry is untouched — it lives in
Aurora, outside the instance entirely, so it now survives instance *replacement* too, not
just a restart.

**Step 1 — get the new image digest**

```sh
crane digest 749549498353.dkr.ecr.us-east-1.amazonaws.com/agents:0.2.0
```

**Step 2 — update `infrastructure/terraform.tfvars`**

```hcl
app_version = "0.2.0@sha256:<digest from step 1>"
```

**Step 3 — apply and roll out**

```sh
just deploy
```

That runs `terraform apply` and then `just restart`. Terraform should show only
`aws_ssm_parameter.app_version` being updated in place — if the plan wants to replace
`aws_instance.app`, something changed `user_data`, which is worth understanding before
confirming. `just restart` then restarts the unit over SSM (no SSH, no open port) and
polls `app_url/health` from your machine until it answers, so a green run has exercised
the whole path a user takes: tailnet, `tailscale serve`, then the app.

The frontend ships inside that image, so there is no separate frontend deploy.

Changing config works exactly the same way. `allowed_emails`, `allowed_service_accounts`,
`google_client_id` and the derived `app_base_url` are all parameters now, so editing one
in `terraform.tfvars` and running `just deploy` takes effect on the restart.

### One-time: create the app's database role

After the **first** apply, the IAM-authenticated role has to be created once. The app
cannot do it itself — it holds no password, and a role that could grant `rds_iam` is
exactly what it must not have:

```sh
just db-bootstrap
```

That reads the AWS-managed master password from Secrets Manager **on your machine**,
opens an SSM port forward through the instance, and runs the `CREATE ROLE` /
`GRANT rds_iam` SQL. The master password is never given to the instance, so this is the
one operation that uses your own AWS credentials rather than the instance's. It is
idempotent, and only needs re-running if `db_app_username` changes.

Until it has run, the app starts and fails its health check with an authentication
error — which is the boot gate doing its job.

**What still replaces the instance:** rotating `google_client_secret` or the session
secret, and changing the AMI, instance type or the Tailscale settings — plus anything
else that edits the systemd unit, which is why the move to Aurora replaced it once. That
is now a downtime event and nothing more: the pantry lives in the database, so an
instance can be rebuilt without losing anything. Secret rotation is
deliberate — a hash of each secret is embedded in `user_data` so the instance is rebuilt
rather than relying on someone remembering to restart it. Those are the cases the
paragraph below applies to.

When the instance *is* replaced: a machine name in Tailscale stays reserved by whatever still holds it, so the shutdown has to *delete* the retired node, not just disconnect it — otherwise the replacement joins as `agents-1` while `app_url` and the OAuth redirect URI still point at `agents`, and the deploy silently lands nowhere. That is what the ephemeral auth key buys: `tailscale logout` in the unit's `ExecStop` removes the node outright, and only works because the node is ephemeral. It depends on a graceful shutdown, so it does **not** cover an instance that is killed rather than stopped — Tailscale reaps an idle ephemeral node on its own, but [only after 30–60 minutes](https://tailscale.com/kb/1111/ephemeral-nodes). Replace inside that window and the name is still taken.

Auth-related variables live alongside `app_version` in `terraform.tfvars` — see
`terraform.tfvars.example`. `google_client_secret` and a generated session key are stored
as SSM `SecureString` parameters, and the non-secret config as plain `String` parameters;
all of them are fetched by the systemd unit at start rather than rendered into EC2 user
data, where anything on the box could read them and where every edit would cost a new
instance. There is no `app_base_url` variable: the app has exactly one origin now, so it
is derived from `tailscale_hostname` and `tailscale_tailnet` and surfaced as the `app_url`
output.

If a restart fails, the unit fails loudly rather than starting with half a configuration —
a required parameter that cannot be fetched aborts the start, leaving the previous
container's environment file untouched. `just ssh` then `journalctl -u agents.service` has
the detail.

If the app ever comes up as `agents-1.<tailnet>.ts.net`, a retired node is still holding
the name. Delete it from the admin console's machine list, then replace the instance again
(`terraform -chdir=infrastructure apply -replace=aws_instance.app`) — renaming the new node
in the console is not enough, because the `-1` suffix sticks even after the conflict is
gone.

To get a shell on the running instance:

```sh
just ssh
```

It reads `ec2_instance_id` from the terraform state and hands it to `aws ssm
start-session`, so it needs no SSH key and no inbound port — the instance has neither.
Runs from anywhere in the repo. Extra arguments are passed through to `aws ssm
start-session`, e.g. `just ssh --profile prod`.

## Development

```sh
just dev            # start both servers with hot-reload
just serve          # build the frontend and serve everything from :8000, like production
just docker-run     # build and run the production image on :8080
just docker-check   # build the production image and smoke-test it (mirrors the CI docker job)
just check          # run all checks (mirrors CI)

just backend-test   # pytest (starts a throwaway Postgres container)
just backend-lint   # ruff check
just backend-fmt    # ruff format --check

just db-up          # local Postgres on :5432
just db-reset       # wipe it and start clean
just db-psql        # psql shell on it

just db-tunnel      # forward a local port to Aurora through the instance (SSM)
just db-bootstrap   # one-time: create the IAM-authenticated role in Aurora

just frontend-test  # vitest
just frontend-lint  # eslint
just frontend-build # next build (type-check + compile)
```

### How the tests use Postgres

The store is almost entirely SQL, so testing it against a fake would test the fake.
`backend/conftest.py` starts a `postgres:17-alpine` container once per session with
[testcontainers](https://testcontainers.com/) and truncates between tests — the same
major version Aurora runs. That makes Docker a prerequisite for `just backend-test`. Set
`TEST_DATABASE_URL` to use a server you already have instead, bearing in mind the
fixtures truncate, so do not point it at anything you want to keep.

`just smoke` starts a Postgres container of its own — separate from the `just db-up` one,
on a private Docker network, empty every run — and points the image at it. That is the
seam neither unit test can see: whether the built image can really open a connection and
create its schema, rather than whether the SQL is right. `just docker-check` builds the
image and runs it, which is what the CI `docker` job does.

`scripts/smoke_test.py` checks a running container end to end: that `/health` reports a
database it actually reached, `/` serves the React app, `/api/*` still reaches FastAPI
rather than the static mount, and `/pantry` redirects to `/pantry/`. It is stdlib-only, so
CI runs it without installing anything. Point it at any deployment:

```sh
python3 scripts/smoke_test.py "$(terraform -chdir=infrastructure output -raw app_url)"
```
