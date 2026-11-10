# Dagger performance plan

Started November 9, 2026. Preserve fresh Socket policy enforcement, full-source
security analysis, generated-code checks and both production architectures.

## Baseline

Three successful GitHub Actions runs showed check-step durations of 4m15s–5m49s.
Individual check timings overlap and include shared dependencies; they cannot be
added to predict wall-clock savings.

| Check | Observed duration |
| --- | --- |
| ARM64 image | 64–116s |
| AMD64 image | 50–89s |
| Backend tests | 56–63s |
| Module contracts | 41–58s |
| SDK generation/staleness | 39–56s |

Evidence:

- [PR run](https://github.com/ryandens/agents/actions/runs/42741837347)
- [Dependency-update run](https://github.com/ryandens/agents/actions/runs/42740800747)
- [Main run](https://github.com/ryandens/agents/actions/runs/42740729792)

OpenGrep's report-export invocation adds 23–32s after the suite. Its session cache
and random scan key deliberately force a second scan in the new session. The main
run also spent 32s exporting the already-built image, including fresh policy gates.

A local frontend check on the pinned beta.25 engine spent 3m26s in `serveModule`
before dependency installation. It was interrupted; this is not a completed cold
or warm build benchmark. Container operations before the policy install showed
cache hits. The host PATH CLI was beta.11: use `nix develop` consistently.

## Iterations

### 1. Share the authoritative frontend build

- [x] Extract a shared, filtered production Docker build context.
- [x] Have `frontend-dist` export `/src/out` from the Dockerfile `frontend` stage.
- [x] Keep its fresh frontend Socket gate and the existing blocked-policy contract.
- [ ] Verify frontend build, module contracts, both images and generated clients.
- [ ] Compare an unchanged repeat run and a frontend-source edit; inspect whether
      the Dockerfile frontend stage is reused by image builds.

This removes the separate native Dagger compilation path without changing the
Dockerfile's native BUILDPLATFORM frontend behavior or making image checks optional.

### 2. Scan OpenGrep once per CI run

- [ ] Find a supported way to run discovered checks and export their reports in
      one Dagger session, retaining the same scanner result and fresh remote rules.
- [ ] Preserve SARIF export after findings and unrelated application failures,
      scanner-error failures, and GitHub upload failure behavior.
- [ ] Verify one real scanner execution, valid SARIF, and failure cases.

Do not remove the per-session scan key or cache mutable registry rules indefinitely
to avoid duplicate work. A shell wrapper alone may still create separate sessions;
prove reuse before changing CI.

### 3. Narrow function cache invalidation

- [ ] Separate the random Socket policy key from deterministic function receiver
      state, keeping explicit fresh gates at every workload entry point.
- [ ] Pass filtered source inputs to deterministic operations so unrelated edits
      do not invalidate their function results.
- [ ] Exercise newly blocked policy against an otherwise warm workload and prove
      all image/export/publish, frontend, backend, CLI and smoke gates still apply.

The current key invalidates application function results, but normal container
operations below those functions can still be cached. Measure orchestration savings
separately from package-download and compilation savings.

### 4. Benchmark frontend filesystem caching

- [ ] Persist the appropriate Next.js build-cache directory on the authoritative
      build path, without using a cache mount as the sole copy of output artifacts.
- [ ] Check the pinned Next.js version's Turbopack production filesystem-cache
      behavior. Its documented opt-in is experimental; evaluate separately.
- [ ] Compare clean, unchanged and edited-source builds and check output integrity.

References: [Next.js CI caching](https://nextjs.org/docs/app/guides/ci-build-caching)
and [Turbopack filesystem caching](https://nextjs.org/docs/app/api-reference/config/next-config-js/turbopackFileSystemCache).

### 5. Verify engine persistence and execution overhead

- [ ] Investigate local `serveModule` latency with verbose traces and the pinned
      CLI/runtime, without clearing or restarting a shared engine as a shortcut.
- [ ] Verify actual cross-job cache hits in CI; the Cloud token alone is not
      evidence that ephemeral GitHub runners restore build layers or cache volumes.
- [ ] Evaluate persistent-engine options only after confirming cache misses.
- [ ] Benchmark `-j 2` versus higher concurrency on suitable runner resources;
      retain both architectures and measure emulation separately.

## Validation and progress

Record each iteration's changes, commands, outcomes and limitations here. Do not
claim a speedup from source inspection alone. Run targeted checks first, then the
full suite when the local engine permits meaningful validation. No deployment or
publication is needed for these iterations.

### Iteration 1 implementation

Added `_production_source` in `.dagger/src/agents_ci/__init__.py` and reused it in
`frontend_dist` and `image`. `frontend_dist` now awaits its existing fresh Socket
gate and exports the Dockerfile's `frontend` stage. The production Dockerfile,
image policy gates and frontend lint/test containers are unchanged. Updated the
pipeline guide to describe the shared build path.

Passed:

- `.venv/bin/ruff check .dagger/src/agents_ci/__init__.py`
- `.venv/bin/ruff format --check .dagger/src/agents_ci/__init__.py`
- `git diff --check`
- AST comparison against HEAD: module function signatures, return types and
  decorators are unchanged, so this patch does not change the generated API.
- The existing `AgentsCi._assert_policy_gates()` contracts, run on the host using
  the vendored SDK and generated clients. Only `Query.default_platform` was stubbed
  with `unittest.mock.AsyncMock`; the contracts passed for both `linux/amd64` and
  `linux/arm64`. This verifies blocked workloads stop at their policy gates; it does
  not replace a real build or the remaining scanner/module contracts.

Runtime validation remains pending:

```sh
nix develop --no-write-lock-file --command dagger check \
  --generated=false --check frontend-build --check module-contracts \
  -j 2 --progress plain -vv
```

This stalled while serving `/dagger/socket-firewall` on the shared beta.25 engine
and on a fresh, dedicated beta.25 engine. The isolated run was interrupted after
3m34s in the selected checks; its trace reported waiting on `Host.directory` during
`serveModule`. No application install or compilation was reached. This reproduces
the blocker independently of the shared engine's cached state, without establishing
its root cause. The temporary engine and its dedicated cache volume were removed;
the shared engine and cache were preserved.

Diagnostic logs remain local at `/tmp/agents-dagger-performance-iteration1.log`
and `/tmp/agents-dagger-performance-isolated.log`. Dependencies for the host
contract check were prepared using Socket-protected `sfw uv run`; the final test
ran offline. No SDK, engine or lockfile pins changed.

Next action: diagnose the nested local-module `Host.directory`/`serveModule` stall
before expanding the patch. Then finish iteration 1's real build, image and repeat
run checks. No measured performance improvement is claimed yet.
