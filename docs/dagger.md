# Dagger pipeline

Dagger runs application checks, protected installs, production builds and smoke
tests using the same code locally and in GitHub Actions. The application module is
in `.dagger`; independent Socket, Datadog, OpenGrep, Actionlint and Renovate config modules live
under `dagger/`.

## Running locally

Install [Nix](https://nixos.org/download/) and start Docker. Enter the locked
shell with `nix develop`. For automatic activation, install direnv with nix-direnv
and run `direnv allow`. The shell provides
Dagger, just, Python, Git and the Docker client on Linux (amd64/arm64) and
Apple Silicon macOS. Docker's
daemon is provided by Docker Desktop or your normal host setup.

`flake.lock` pins the official Dagger Nix package and nixpkgs. The shell asserts
that Dagger matches `.dagger-version`; review CLI-pin and lockfile updates together.
The Python SDK is separately pinned in `dagger.toml`, and `dagger.lock` records
resolved module sources and images. Standard SDK generation selects the native
Python runtime; the legacy generated Dang entrypoints have been removed.

From the shell:

```sh
dagger check -j 2 --progress report  # Application, image, workflow and security checks
dagger check --generated=false --check backend-test
dagger check --generated=false --check cli-test
dagger check --generated=false --check frontend-test
dagger check --generated=false --check smoke
dagger check --generated=false --check datadog --check opengrep
dagger generate -y                 # Ruff fixes/formatting and SDK/client updates
```

Use `dagger check -l --generated=false` to list exact names. In particular,
the generated architecture check names are `image-amd-64` and `image-arm-64`.

Dagger runs directly against the checkout. Workspace ignores in `dagger.toml`
and module-manifest input filters exclude environments, caches, credentials,
Terraform state and agent worktrees. No temporary checkout or generated-file
copy-back is involved.

Local `uv`/pnpm installs remain available for hot reload and editing. Safari's
dedicated virtualenv, Full Disk Access and launchd operations remain host tasks.
Linux tests use synthetic Safari databases and need no privacy permissions.

## What the pipeline checks

- Ruff lint fixes and formatting through the pinned typesafe-ai module.
  `dagger generate` applies changes; `dagger check` includes generated-file drift checks.
  The module detects Ruff from `uv.lock` and excludes vendored SDK/client code.
- Independent pytest, ESLint, Vitest and frontend-build checks.
- Datadog and OpenGrep policy checks covering the same full source locally and in CI.
- Actionlint, ShellCheck and pyflakes for GitHub Actions workflows.
- Renovate repository configuration validation using its pinned official image.
- Postgres 17 through `TEST_DATABASE_URL`; no host Docker socket is passed to tests.
- Fresh Socket checks for backend, CLI build dependencies and frontend downloads.
- Both production image architectures using `backend/Dockerfile` as the build source.
- Alembic migration and frontend/API/CLI smoke checks with a separate disposable
  database. Any smoke skip fails this check.
- Reusable-module failure contracts, Socket pin consistency,
  and generated-code staleness.

Datadog and OpenGrep also expose report-producing commands so CI can upload
findings even when policy fails. `dagger api call datadog-report export --path
reports/datadog` (or `opengrep-report`) exports SARIF, logs and policy status. A
successful export does not mean policy passed: read `exit-code` or run the check.
The analyzer image needs no Datadog API/application keys. The standard suite and report exports scan all source; there is no separate PR-diff
selection layer.

Normal builds cache dependencies before copying source. Every application test,
frontend build and image operation first awaits the relevant fresh Socket policy
check. A random key captured when the app module is created and empty package
caches force a policy refresh; all callers share that key and Dagger deduplicates
the fresh installs within the invocation. A newly blocked policy therefore stops
cached workloads before they execute. The same gates apply to image export and
publishing. Failure contracts exercise these dependency edges.

Every uv/pnpm install also runs through Socket, including production Dockerfile
installs. These gates cover application registry dependencies; base images, OS
packages and third-party module runtimes have their own supply chains. Socket is
excluded from the final runtime image.

The app constructor captures a scoped, content-addressed source Directory and a
fresh policy key as explicit receiver fields. The policy key refreshes the gates
for each invocation, while unchanged workload container operations remain cached.
Publishing explicitly disables function caching.

## CI and releases

One `dagger` CI job runs the same suite used locally:

```sh
nix develop --no-write-lock-file --command dagger check -j 2 --progress report
```

Dagger discovers application, image, pipeline and generated-code checks, shares
their dependency graph, and reports individual results. Adding a
check does not require another GitHub job or another filter list in YAML.

The same job exports Datadog results, uploads SARIF and enforces scan policy.
These steps still run after an application check fails. On main, it also exports
the production image for Trivy and uploads its findings. Scanner or upload failures
fail the job; an earlier failed check remains a failure after reports are uploaded.
OpenGrep uses the same report/export/policy pattern in this job. Reports cover the
same full source as the default checks, so unchanged-file findings are also uploaded.
Actionlint and Renovate config validation are discovered checks in the main
suite. Promptfoo retains its own workflow. The first adoption layer's shadow status
is temporary. CI and release jobs pass the repository's `DAGGER_CLOUD_TOKEN` secret
to every Dagger invocation for Cloud connectivity. Fork PRs without the secret
can still run on the local engine.

Require `dagger` in branch protection when promoting the second adoption layer,
and remove retired backend/CLI statuses; the frontend, Datadog and Docker statuses
retire in their respective layers. Actionlint and OpenGrep statuses retire in the
final module-extraction layer; Renovate validation also moves into `dagger`.
Repository rules must match the layer being merged.

Tagged releases run the full Dagger check suite before acquiring AWS OIDC credentials.
The explicit `publish` function receives the ECR password as a Dagger Secret and
publishes both platforms, returning the manifest digest for the job summary. It is
not a check and is never invoked by `dagger check`. No release is published by local
validation. Deployment remains `just deploy`, including the complete Terraform plan
and intended replacements as required by `AGENTS.md` and the deployment README.

## Secrets and host operations

Dagger supports 1Password references directly for Secret arguments:
`dagger api call publish --password=op://vault/item/field ...`.
The caller needs an authenticated `op` CLI or a service account session. The agent
shell needs its own session; authentication in another terminal is not inherited.
Use Dagger Secret inputs for pipeline credentials instead of loading local env files.
See [Dagger secrets](https://devel.docs.dagger.io/config/secrets/).

Just retains operations that manage persistent host state: hot reload and local
installs, local database administration, SSH/SSM tunnels, Safari permissions and
launchd, and the full Terraform deployment. `just env-sync` merges 1Password values
into host `.env` and `terraform.tfvars`, preserving local settings and restrictive
permissions. Its host-file merge is distinct from passing a secret into a container;
1Password support itself is not a reason to keep a pipeline task in Just.
`just frontend-build` materializes the static export for `just serve`.
`just docker-build` builds through Dagger and loads the archive into the host Docker
daemon as `agents:local`; `just docker-run` uses that image with the local database.
Use the Dagger `smoke` check for disposable integration tests.

## Updating and extracting modules

Review CLI, SDK and generated-client updates together. After updating an SDK or
module API, run `dagger generate -y`, inspect the generated diff, and run the suite.
Renovate excludes vendored SDK/client code from dependency extraction. Socket updates
group versions and both artifact digests; Datadog uses a version/digest image pin.

The [Socket](../dagger/socket-firewall/README.md),
[Datadog](../dagger/datadog-static-analyzer/README.md),
[OpenGrep](../dagger/opengrep/README.md) and
[Actionlint](../dagger/actionlint/README.md) and
[Renovate config](../dagger/renovate-config/README.md) modules have no application dependencies. To publish later, move a complete module directory into the chosen
Daggerverse, add its fixtures to that repository's CI harness, choose a license and
module-scoped release tags, then replace the app client's local dependency address
with the published Git reference and regenerate. No external repository is created
or publication performed by this adoption.

The Ruff dependency is the reviewed typesafe-ai Dagger 1.0 implementation, pinned
to a commit because the latest module release still uses the older client API.
See its [generator implementation](https://github.com/typesafe-ai/daggerverse/blob/d536bce38cd73b4e66a757c5687bbbd51ac8ab5b/ruff/src/ruff/main.py).
We follow its native configuration discovery and changeset-based fixes, while
retaining Socket-protected Python installs in our app builder. Reusing a builder
must preserve that install policy, not just produce the same virtualenv.
Paper Compute's [Tapes module](https://github.com/papercomputeco/tapes/blob/main/.dagger/main.go)
also illustrates shared container foundations, explicit source exclusions and
Postgres service bindings. Its [PR workflow](https://github.com/papercomputeco/tapes/blob/main/.github/workflows/pr.yaml)
uses direct Dagger execution through Nix; our CI also cancels superseded PR runs.

Design rationale and reference research are in [the adoption proposal](dagger-adoption.md).

## Stack

Merge order: Socket/CLI → backend → frontend → Datadog/images → releases →
OpenGrep/Actionlint/Renovate module extraction → Nix environment and direct execution
→ complete Dagger checks and reuse upstream Ruff.
Each PR targets its predecessor; retarget the next PR to main after merging.
After squash-merging a layer, restack/rebase descendants onto updated main before
retargeting; merge commits preserve the existing ancestry.
