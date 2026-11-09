# Dagger pipeline

Dagger runs application checks, protected installs, production builds and smoke
tests using the same code locally and in GitHub Actions. The application module is
in `.dagger`; independent Socket, Datadog, OpenGrep and Actionlint modules live under `dagger/`.

## Running locally

Install Docker, a Dagger CLI supporting `--x-release`, Python 3 and just. Start
Docker before running checks. `scripts/dagger` selects `.dagger-version` without
replacing an existing CLI. The SDK is separately pinned in `dagger.toml`, and
`dagger.lock` records resolved sources and images. Dagger Cloud is optional.

```sh
just check                         # Application, image, workflow and security checks
just backend-check                 # Ruff, format, pytest, fresh Python Socket check
just cli-check
just frontend-check
just docker-check                  # Both architectures and native smoke test
just dagger-check --check backend-test
just datadog-check                  # SARIF and status under reports/datadog
just opengrep-check                 # SARIF and status under reports/opengrep
just dagger-generate               # After changing a module's exposed API
```

Use `scripts/dagger check -l --generated=false` to list exact names. In particular,
the generated architecture check names are `image-amd-64` and `image-arm-64`.

The local wrapper snapshots Git-tracked files and nonignored new files into a
temporary workspace. It includes current edits and deletions; `.env`, ignored
environments, Terraform state/providers, and agent worktrees stay outside the
engine. This bounds the enclosing context read by the beta Python runtime.
Generated SDK/client/config changes are copied back only after success, and a
concurrent host edit prevents overwrite. Explicit artifact exports should use
absolute host paths, as the just recipes do. CI uses its clean checkout directly.
`DAGGER_USE_HOST_WORKSPACE=1` opts into direct execution for diagnosis.

Local `uv`/pnpm installs remain available for hot reload and editing. Safari's
dedicated virtualenv, Full Disk Access and launchd operations remain host tasks.
Linux tests use synthetic Safari databases and need no privacy permissions.

## What the pipeline checks

- Independent Ruff, format, pytest, ESLint, Vitest and frontend-build checks.
- Actionlint, ShellCheck and pyflakes for GitHub Actions workflows.
- Postgres 17 through `TEST_DATABASE_URL`; no host Docker socket is passed to tests.
- Fresh Socket checks for backend, CLI build dependencies and frontend downloads.
- Both production image architectures using `backend/Dockerfile` as the build source.
- Alembic migration and frontend/API/CLI smoke checks with a separate disposable
  database. Any smoke skip fails this check.
- Reusable-module failure contracts, Socket pin consistency, pipeline lint/tests,
  and generated-code staleness.

Datadog is a separate report-producing command so CI can upload failed findings.
Its default scan includes application and pipeline source. PR selection is owned by
`scripts/prepare_datadog_scan.py`; deletions, renames, empty diffs and rule changes
have focused tests. The analyzer image needs no Datadog API/application keys.

Normal builds cache dependencies before copying source. Fresh Socket checks use
unique execution keys and empty package caches; cached builds alone do not recheck
current Socket policy. The Dockerfile also verifies and invokes Socket for production
installs. Socket is excluded from the final runtime image.

The app constructor receives the caller's Workspace and captures a scoped,
content-addressed source Directory. That Directory is an explicit receiver field,
so changes outside the module invalidate affected functions without relying on an
ambient workspace lookup. Functions and container operations still reuse unchanged
inputs. Fresh Socket checks and publishing explicitly disable function caching.

## CI and releases

One `dagger` CI job runs `scripts/dagger check -j 2 --progress report`, the same
suite used locally. Dagger discovers application, image, pipeline and generated-code
checks, shares their dependency graph, and reports individual results. Adding a
check does not require another GitHub job or another filter list in YAML.

The same job exports Datadog results, uploads SARIF and enforces scan policy.
These steps still run after an application check fails. On main, it also exports
the production image for Trivy and uploads its findings. Scanner or upload failures
fail the job; an earlier failed check remains a failure after reports are uploaded.
OpenGrep uses the same report/export/policy pattern in this job. PR source selection
is owned by `scripts/prepare_opengrep_scan.py`, while local and main scans cover all
source. Actionlint is a discovered check in the main suite. Promptfoo and Renovate
retain their own workflows. The first adoption layer's shadow status is temporary.

Require `dagger` in branch protection when promoting the second adoption layer,
and remove retired backend/CLI statuses; the frontend, Datadog and Docker statuses
retire in their respective layers. Actionlint and OpenGrep statuses retire in the
final module-extraction layer. Repository rules must match the layer being merged.

Tagged releases run the full Dagger check suite before acquiring AWS OIDC credentials.
The explicit `publish` function receives the ECR password as a Dagger Secret and
publishes both platforms, returning the manifest digest for the job summary. It is
not a check and is never invoked by `just check`. No release is published by local
validation. Deployment remains `just deploy`, including the complete Terraform plan
and intended replacements as required by `AGENTS.md` and the deployment README.

## Updating and extracting modules

Review CLI, SDK and generated-client updates together. After updating an SDK or
module API, run `just dagger-generate`, inspect the generated diff, and run the suite.
Renovate excludes vendored SDK/client code from dependency extraction. Socket updates
group versions and both artifact digests; Datadog uses a version/digest image pin.

The [Socket](../dagger/socket-firewall/README.md),
[Datadog](../dagger/datadog-static-analyzer/README.md),
[OpenGrep](../dagger/opengrep/README.md) and
[Actionlint](../dagger/actionlint/README.md) modules have no application dependencies. To publish later, move a complete module directory into the chosen
Daggerverse, add its fixtures to that repository's CI harness, choose a license and
module-scoped release tags, then replace the app client's local dependency address
with the published Git reference and regenerate. No external repository is created
or publication performed by this adoption.

Design rationale and reference research are in [the adoption proposal](dagger-adoption.md).

## Stack

Merge order: Socket/CLI → backend → frontend → Datadog/images → releases →
OpenGrep/Actionlint extraction.
Each PR targets its predecessor; retarget the next PR to main after merging.
After squash-merging a layer, restack/rebase descendants onto updated main before
retargeting; merge commits preserve the existing ancestry.
