# Dagger performance plan

Started November 9, 2026. Preserve fresh Socket policy enforcement, full-source
security analysis, generated-code checks and both production architectures.

## Handoff: direct Dagger entry points required

**User decision:** invoke `dagger check` and other Dagger commands directly.
Do not delegate Dagger to Just and do not introduce a separate Python/GraphQL
runner for discovery, concurrency, authentication, check execution or reports.
Just remains appropriate for existing persistent host operations such as deploy,
local database administration and Safari permissions.

### Current code and PR state

- [PR #569](https://github.com/ryandens/agents/pull/569) is merged. Main commit
  `10979eda97de2200ac8ddeda502ce2b6217bdc1f` shares the Dockerfile frontend stage.
- [PR #570](https://github.com/ryandens/agents/pull/570) is a draft handoff. The
  custom-runner implementation was rejected for duplicating Dagger orchestration.
  It has been removed from the branch tip, including its Just recipe, runner tests,
  extra Dagger test check and workflow changes. The tip keeps direct native CLI
  invocation and the baseline 20 discovered checks. This PR now changes only this
  plan; it does not ship the next performance fix.
- Prototype commit `d95fbc0077cd6885ebf327c6446ccb3282fe6647` remains in Git history
  for experimental evidence. Do not restore its architecture as the solution.
- Branch: `codex/dagger-filtered-check-session`; worktree:
  `/private/tmp/agents-dagger-session-pr`. Fetch the branch from GitHub if the
  temporary worktree is missing. A temporary-directory cleanup already removed it
  once; its staged index was used to recover the prototype before it was pushed.
- The shared checkout `/Users/ryandens/git/ryandens/agents` is detached at
  `381459e`, with uncommitted leftovers from the already-merged #569 and a local
  copy of this plan. Preserve those files; continue from current main in a worktree.
- Commits use the repository's conventional-gitmoji skill. Git enables SSH signing
  through 1Password; signing previously waited for its approval prompt. Do not
  disable signing to bypass it. `op` shell login is a separate issue.

### Next agent: outstanding work

1. Keep the native CLI architecture. Investigate a small Dagger-native or upstream
   fix for nested local module loading; more workspace ignore patterns alone do
   not fix the identified engine path. Verify a newer engine actually fixes it
   before changing pins. Do not hand-edit generated clients or clear user caches.
2. Complete iteration 2 with native Dagger capabilities: share an OpenGrep scan
   between check and SARIF export while retaining fresh rules per invocation and
   report export after application/policy failures. Core `Check.report` exists,
   but producing/exporting it through the pinned SDK/CLI has not been investigated.
   This is an investigation lead, not a validated implementation. A shell wrapper
   invoking multiple Dagger commands does not establish a shared session.
3. Preserve the full baseline check set: application tests, both image architectures,
   smoke, module contracts, Socket gates, Ruff and SDK generated-code staleness.
   Verify native discovery with `dagger check --list --format link`. Baseline links
   use the `dag+check://` prefix; artifact API links used `dag://` in the prototype.
4. Then tackle iterations 3 and 4 independently: isolate the random policy key from
   unrelated deterministic function state, and benchmark Next.js compilation
   caching. Prove newly blocked policy still stops otherwise cached workloads.
5. Finish unchanged/source-edit frontend reuse measurements and cross-job engine
   cache verification. A Cloud token alone is not evidence of persistent caching.
6. Open incremental PRs as work becomes reviewable, run appropriate checks, and
   leave merging and deployment to the user. No release or Terraform changes are
   needed for this performance work.

### Evidence and validation limits

- Pinned CLI/engine: `v1.0.0-beta.25`; engine source commit `a45241b2`. The host
  PATH CLI was beta.11, so use `nix develop --no-write-lock-file --command dagger`.
  Python SDK/runtime pins are v1.7.0; reviewing v1.8.0 showed generator import fixes,
  not an established fix for the engine's nested host import. Recheck upstream.
- `core/schema/module_tree.go:hostTreeModuleSource` imports the entire local
  context with only `.git` excluded. Trace evidence showed 3m32s traversing an
  ignored 12 GB `.claude` directory before reaching `.venv`. The same problem was
  reproduced on a fresh engine; the shared engine/cache was never reset.
- A Directory-backed, explicitly filtered Workspace avoided that import. The
  prototype discovered the original 20 checks in 7.6s with a roughly 10 MB upload,
  and real module contracts completed from the original checkout in 57.7s.
  This validates the engine-path diagnosis, not the rejected runner architecture.
- Prototype native/API discovery matched 21 checks only because it added its own
  runner test. The accepted baseline remains 20 after removing that prototype.
- Prototype scanner/workflow/runner checks and both SARIF exports passed in 43.7s.
  Trace [3091a3fab088caa88ac14e633c7f2760](https://dagger.cloud/ryandens/traces/3091a3fab088caa88ac14e633c7f2760)
  had exactly one real OpenGrep process for check plus export. Both policy codes
  were zero. A real failed scan also failed the run while both reports exported.
- Its 11 unit tests and Ruff passed, but those tests belonged to the rejected
  runner and were removed with it. They are not validation of a future native fix.
- Prototype [CI run 42941655616](https://github.com/ryandens/agents/actions/runs/42941655616)
  was still running at the last observation; Promptfoo passed. Check the run for
  any useful diagnostics. A later documentation/revert push may supersede it.
- `/tmp` logs and diagnostic scripts were cleared between sessions. Durable
  evidence is in this plan, Git history, linked CI runs, engine source and Cloud
  traces. Do not assume the old local log paths below still exist.
- No whole-suite performance improvement is established by these experiments.

Historical investigation follows. The iteration 2 prototype below is superseded
by this handoff and must not be interpreted as completed production work.

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
- [x] Verify frontend build, module contracts, both images and generated clients
      through the full GitHub Actions check suite for PR #569.
- [ ] Compare an unchanged repeat run and a frontend-source edit; inspect whether
      the Dockerfile frontend stage is reused by image builds.

This removes the separate native Dagger compilation path without changing the
Dockerfile's native BUILDPLATFORM frontend behavior or making image checks optional.

### 2. Scan OpenGrep once per CI run

- [ ] Find an acceptable Dagger-native way to run checks and export their reports in
      one Dagger session, retaining the same scanner result and fresh remote rules.
- [ ] Preserve SARIF export after findings and unrelated application failures,
      scanner-error failures, and GitHub upload failure behavior.
- [ ] Verify one real scanner execution, valid SARIF, and failure cases in the native replacement.

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

- [x] Investigate local `serveModule` latency with verbose traces and the pinned
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

### PR and validation follow-up

Opened [PR #569](https://github.com/ryandens/agents/pull/569) from the isolated
worktree `/tmp/agents-dagger-frontend-pr`. The full discovered check suite passed
in [CI run 42745290414](https://github.com/ryandens/agents/actions/runs/42745290414),
including frontend build, both image architectures, module contracts and generated
staleness checks. PR #569 has been merged. The check step took 4m53s; this single
run is not evidence of a
speedup against the earlier baseline. Security report exports, uploads and policy
steps also passed, as did Promptfoo.

The local upload bottleneck is now identified. The isolated-engine verbose trace
shows `Host.directory(path: repositoryRoot, exclude: [".git"])` during the nested
`serveModule` call, then 3m32s traversing `.claude` before reaching `.venv`. Local
sizes were 12 GB for `.claude`, 185 MB for `.venv`, and 1 GB for frontend dependencies.
The pinned engine's `hostTreeModuleSource` implementation imports the entire host
context with only `.git` excluded, confirming this bypasses workspace ignores on
that path. The current upstream implementation still has that unfiltered import.
Adding workspace ignore patterns alone therefore will not resolve this call.

Engine source:
[pinned module_tree.go](https://github.com/dagger/dagger/blob/a45241b2/core/schema/module_tree.go).

A full local suite from the clean 9.5 MB PR worktree progressed
past nested module loading into real Socket installs, frontend tests, module
contracts and image construction. It was stopped after the complete CI suite
passed, avoiding more local cross-architecture emulation; it is not a completed
local suite. The original checkout's local files and caches were preserved.

### Rejected iteration 2 prototype: filtered check session and shared reports

Implemented `scripts/dagger_check.py` using Dagger's supported raw GraphQL API
under `dagger api with-session`. It applies the configured excludes explicitly,
honors Git ignores, and constructs a Directory-backed Workspace in memory before
discovering all Check artifacts. Each check is synchronized once, with failures
aggregated while the remaining checks continue. No temporary checkout, generated
client patch, or extra Python dependency is required.

Added `just check` for local use and switched CI and release validation to this
runner. CI exports both reports from that same workspace and API session after
checks finish. Successful exports set GitHub step outputs; uploads and explicit
policy steps still run after failed application checks. Each report export is
attempted independently. OpenGrep retains its fresh per-session scan key and
mutable-rule refresh; no cross-session scan caching was introduced.

Validation so far:

- The prototype discovered exactly the original 20 checks, including generated
  staleness checks, from the original checkout in 7.6s. Its snapshot excluded
  `.claude` and `.venv`; the filtered upload was approximately 10 MB.
- The finished runner completed the real module contracts in 57.7s from the
  original checkout with its 12 GB `.claude` directory intact. The old nested
  upload had been interrupted after 3m34s without reaching application work.
  This is evidence of removing the upload bottleneck, not a whole-suite speedup.
- Added 11 host unit tests covering failed findings, continued checks and exports,
  independent export failures, missing/unknown selections, missing ignores,
  HTTP/GraphQL failures, and rejection of redirects. They are also a newly
  discovered `check-runner-test` check, bringing the normal suite to 21 checks.
- Real module contracts, runner tests, workflow validation and Datadog passed.
- An initial real OpenGrep finding in the new transport caused the run to fail
  while both valid SARIF reports still exported. Replaced general URL handling
  with a fixed loopback HTTP connection; both scanner policies then passed.
- A successful real run passed the scanner, workflow and runner checks and
  exported both valid SARIF 2.1.0 reports in 43.7s. The engine log for trace
  `3091a3fab088caa88ac14e633c7f2760` contains exactly one real OpenGrep scan process
  start, proving that its check and report export shared the scan. Both exported
  policy exit codes were zero.
- Ruff lint/format checks and `git diff --check` passed.

This prototype is superseded by the handoff above. Iteration 2 remains open for
a native Dagger implementation. Keep subsequent cache invalidation and compilation
cache changes separate. No merge or deployment is part of this work.
