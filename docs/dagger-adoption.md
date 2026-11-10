# Dagger adoption proposal

Status: original design, researched November 7, 2026. See [the pipeline guide](dagger.md)
for the implemented commands, coverage and remaining hosted integrations.

## Recommendation

Use Python for the pipeline and reusable modules. Adopt the Dagger 1.0 workspace
model, pin the CLI/engine and SDK together, and commit the generated lockfile.
The local CLI is currently `v1.0.0-beta.11`; verify compatibility with selected
module revisions before wiring CI. Start with explicit source inputs and a small
public API. Use workspace discovery where it removes real configuration duplication.

Separate three responsibilities:

- `datadog-static-analyzer`: a portable analyzer and report-producing API.
- `socket-firewall`: add Socket to a caller's container and execute protected installs.
- `agents`: this application's checks, Postgres, image assembly and smoke tests.

Develop the reusable modules here first. Give each an independent manifest, README
and fixture suite so moving it into `ryandens/daggerverse` changes dependency
addresses rather than its API. Publishing is a later step.

## Lessons from the references

[Typesafe's workspace configuration](https://github.com/typesafe-ai/daggerverse/blob/main/dagger.toml)
separates reusable tools and generates clients for their dependencies.
Its [uv implementation](https://github.com/typesafe-ai/daggerverse/blob/main/uv/src/uv/main.py)
discovers workspace members and scopes build inputs.
Its [Ruff implementation](https://github.com/typesafe-ai/daggerverse/blob/main/ruff/src/ruff/main.py)
reads native version configuration and returns changesets for fixes. Adopt narrow
inputs and native configuration; evaluate its uv builder before writing our own.
Specifically verify that Socket can wrap every dependency-installing execution.
The current builder's applicability to our flat FastAPI layout and Python 3.15
needs an integration trial.

[Paper Compute's Tapes pipeline](https://github.com/papercomputeco/tapes/blob/main/.dagger/main.go)
shares a container foundation and binds a
[Postgres service](https://github.com/papercomputeco/tapes/blob/main/.dagger/postgres.go)
to tests. Its [Docker image module](https://github.com/papercomputeco/daggerverse/blob/main/dockerimage/main.go)
returns buildable containers and publishes platform variants. Adopt these object
boundaries. Its [CI workflow](https://github.com/papercomputeco/tapes/blob/main/.github/workflows/ci.yaml)
still builds images through Buildx, so it is not evidence that every operation
must move to Dagger at once.

[Dagger 1.0](https://dagger.io/changelog/workspaces/) introduces `dagger.toml`
and `dagger.lock`. Use the
[current configuration reference](https://docs.dagger.io/reference/config-files/dagger-toml/)
when implementing; avoid combining older `dagger.json` examples with current SDK
syntax. The beta version is an explicit compatibility choice to validate.

## Coverage and ownership

| Existing behavior | Proposed Dagger responsibility | Integration that stays outside |
| --- | --- | --- |
| Backend Ruff, formatting, pytest | Named checks; disposable Postgres 17 bound through `TEST_DATABASE_URL` | GitHub triggers and aggregate check policy |
| CLI Ruff, formatting, pytest | Independent checks using synthetic Safari fixtures | macOS installation, Full Disk Access and launchd |
| Frontend lint, build, Vitest | Shared frozen install; independent checks; static output as a Directory | Developer hot reload can keep current recipes |
| Datadog analysis | Pinned tool, report object and policy check | SARIF upload permissions and GitHub upload action |
| Actionlint and OpenGrep | Portable checks and report generation in a later increment | GitHub event context and report upload |
| Production image and smoke | Return a Container, migrate disposable DB, start app service, run smoke client | Release trigger and AWS OIDC credential acquisition |
| Trivy | Scan the built artifact with explicit advisory refresh policy | SARIF publication and scheduled release-scan triggers |
| Multiarch release | Build amd64/arm64 variants and publish exact digest | AWS authorization; Terraform deployment through `just deploy` |
| Promptfoo and Renovate workflows | Evaluate individually after core parity | Hosted service integrations and repository maintenance |

Keep `just` as the convenient entry point. As checks migrate, recipes become thin
Dagger invocations. Avoid maintaining the same build logic in just, YAML and Python.
GitHub Actions should eventually orchestrate checkout, Dagger, credentials, artifacts
and status publication. Use one Dagger job for migrated checks and let Dagger own
check discovery, concurrency and detailed results. Promote its aggregate status in
branch protection as native jobs retire; individual GitHub statuses are optional.

## Proposed reusable APIs

These are conceptual contracts, not verified CLI signatures.

### Datadog static analyzer

- Accept source Directory, analyzer version or caller-supplied tool container,
  configuration and failure severities. Default repository configuration remains
  `code-security.datadog.yaml`; retain the current warning/error failure policy.
- Return a scan result exposing SARIF, logs and exit status. A separate assertion
  fails on findings or execution errors. A failed scan must not make its report
  inaccessible; distinguish missing/malformed output from a valid findings report.
- Normalize SARIF paths relative to the repository and test GitHub ingestion.
  Container paths must not become unusable source locations.
- Keep GitHub upload and Datadog account integration outside the core module.
  The existing credential-free scan should continue to work.
- Keep base/head diff selection in the app integration. Initially preserve current
  added/modified-file scanning for PRs and full scanning for main. Include config
  and ignore files, preserve relative paths, handle renames/deletions and empty diffs.
  A rules/config change should trigger a full scan. Evaluate merge-base selection
  explicitly before changing the current base/head comparison semantics.

[Datadog's upstream README](https://github.com/DataDog/datadog-static-analyzer/blob/main/README.md)
documents a container distribution. Trial a pinned image before reproducing the
workflow's archive installer; verify version tags, bundled rules and both Linux
architectures. Keep the existing binary version until an upgrade is separately tested.

### Socket Firewall

- Provide a container transformation that installs a pinned, verified `sfw` binary,
  plus an execution method accepting a caller Container and command argument list.
  Return the resulting Container so dependency outputs compose with later steps.
- Execute `sfw uv sync ...` and `sfw pnpm ... install --frozen-lockfile` inside
  their build containers. Installing Socket on the GitHub runner does not protect
  package downloads inside Dagger or Dockerfile executions.
- Keep Python/Node/pnpm/uv bootstrap separate from protected registry downloads.
  Preserve the current Python one-hour and pnpm eight-hour cooldown configuration.
- Preserve exit codes and fail when the firewall cannot start. Never silently retry
  without protection. Support caller-supplied tool artifacts for deterministic tests.
- Resolve Linux architecture explicitly and verify required runtime libraries and CA
  handling on Debian and Chainguard development images. Keep Socket out of runtime.
- Document network scope: this wraps supported package-manager downloads; it is not
  a general container egress firewall.

[Socket's upstream documentation](https://github.com/SocketDev/sfw-free)
lists uv and pnpm support and free operation without API credentials. The remaining
unknowns are behavior inside Dagger, noninteractive failure, cache use and image
compatibility; prove them with real installs before replacing existing CI protection.

## Caching and reproducibility

Copy dependency manifests and lockfiles before source to preserve installation layers.
Scope backend and CLI source separately while retaining all workspace manifests needed
by uv. Mount cache volumes only for package-manager caches, never as the sole storage
of an artifact returned to another step. Preserve frozen/locked resolution and Python
and Node pins. Avoid a second independently maintained tool-version list.

A cached successful install does not reconsult Socket's current policy. Even rerunning
the command can use a warm package cache without contacting its proxy. Initially add
an explicit fresh-install security check per CI run, using an isolated empty package
cache, while ordinary builds reuse protected dependency layers. Verify what requests
reach Socket; describe this as install-time protection, not continuous revalidation
of every artifact. Separate vulnerability auditing can cover already cached packages.

Use source/version/config keys for deterministic checks. Advisory-backed scans need
an explicit refresh schedule. Do not add timestamps to every container: that destroys
useful cache sharing. Commit Dagger's lockfile and arrange reviewed updates alongside
Renovate's existing pins; confirm manager support before adding custom extraction.

## Image and smoke-test migration

First wrap the existing Dockerfile in a Dagger image function to establish image and
smoke parity. This step retains its unprotected dependency installs and must not be
described as closing Socket coverage. Then move dependency preparation and assembly
into composable Dagger containers, or deliberately revise Dockerfile install steps to
invoke Socket. Choose one authoritative production build once parity is established.

Preserve Chainguard runtime, nonroot execution, backend-only runtime dependencies,
frontend static export, entrypoint and Alembic deployment behavior. Share the frontend
artifact across target platforms; build Python dependencies for each runtime platform.
Prove interpreter and ABI compatibility when copying the environment to runtime.

Bind app and migration containers to disposable Postgres services. Use separate DB
instances for destructive pytest fixtures and smoke checks. The existing
`TEST_DATABASE_URL` hook avoids mounting the host Docker socket for backend tests.
Ensure the smoke client includes uv, CLI source and its workspace metadata: current
smoke checks skip the CLI/API seam when those inputs are absent. Require zero
unexpected skips in the Dagger smoke check.

## Delivery sequence and acceptance

1. Bootstrap a pinned workspace and SDK; add the independent reusable module skeletons.
   Trial Typesafe uv composition and record the supported CLI/SDK/module revisions.
2. Implement Socket first, then backend, CLI and frontend checks. Run beside existing
   CI until results agree. Prove clean, warm-cache, blocked-install and network-failure
   behavior without fallback. Test tool installation on amd64 and arm64.
3. Implement Datadog reports and checks. Test a clean fixture, known finding, scanner
   failure, empty diff and config change. Verify SARIF export after failure and paths
   in GitHub code scanning before replacing the existing job.
4. Migrate image/smoke and protected release installs. Exercise migrations, nonroot
   runtime, frontend/API/CLI seams and both release architectures before switching
   publishing. Retain AWS OIDC and return the published manifest digest.
5. Move remaining portable scanners; remove redundant YAML setup and recipes. Measure
   cold/warm CI time and input invalidation. Keep independent failure reporting.
6. Extract the two reusable modules after APIs have survived real usage. Publish
   independent module versions with fixtures, changelogs and compatibility notes.
   [Typesafe's release workflow](https://github.com/typesafe-ai/daggerverse/blob/main/.github/workflows/release.yml)
   provides an example of module-scoped release tags.

The first implementation slice should be Socket plus the three application check
groups. It validates the most important composition and caching decisions before
adding SARIF, image publication or infrastructure side effects.
