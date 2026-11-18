# Dagger CI baseline and cache investigation

Measured November 16, 2026 (America/Los_Angeles; run timestamps are November 17 UTC).
Related performance plan: [PR #620](https://github.com/ryandens/agents/pull/620).

## Recent successful runs

GitHub job and step durations below come from the Actions API. They exclude queue
wait; job duration includes setup and post steps. The checks step also includes
`nix develop` preparation, so it is not pure Dagger execution time. These runs
use different revisions and are an observational baseline, not a controlled
before/after comparison.

| Event | Run | Revision | Entire Dagger job | Checks/report step |
| --- | --- | --- | --- | --- |
| PR | [44027616985](https://github.com/ryandens/agents/actions/runs/44027616985) | `0bd52ad` | 351s | 319s |
| PR | [44025063579](https://github.com/ryandens/agents/actions/runs/44025063579) | `a5fc1fc` | 360s | 327s |
| PR | [44025018007](https://github.com/ryandens/agents/actions/runs/44025018007) | `4eaedeb` | 345s | 314s |
| Main | [44028390722](https://github.com/ryandens/agents/actions/runs/44028390722) | `60a41fb` | 278s | 210s |

PR median job time: **351s (5m51s)**, range 345–360s. Median checks/report step:
**319s (5m19s)**, range 314–327s. All four logs report 20 passed checks. Main is a
separate sample, not evidence that main is inherently faster or cache-warm.

Nix installation took 7–8s. The two SARIF uploads together took 15–17s. In the main
sample, AMD64 image export took 21s, Trivy took 6s and its upload took 7s. The PR
step logs still downloaded Nix store paths during the checks step. Dagger's own
reported execution durations were approximately 303s, 312s and 300s for the PRs,
and 201s for main; the report formatter rounds these values.

Representative PR check durations from run 44025018007: backend 67s, frontend build
44.6s, AMD64 image 31.6s, ARM64 image 81s, module contracts 63s and SDK staleness
53.7s. These overlap and include shared dependencies; do not sum them to predict
savings. The default aggregate concurrency is two active checks.

Trace links retained from logs:

- [PR 44027616985](https://dagger.cloud/ryandens/traces/673c47561e947da833807b50d64f9bb1)
- [PR 44025063579](https://dagger.cloud/ryandens/traces/2fb8caa55e26be8da350424485f8f26b)
- [PR 44025018007](https://dagger.cloud/ryandens/traces/5ede1805950d726dd10530e860604038)
- [Main checks](https://dagger.cloud/ryandens/traces/4d3193555735505ca8a4d2ebedcb8885)
- [Main image export](https://dagger.cloud/ryandens/traces/9a9718f7a196c83327db87ab965e4225)

## Controlled cache experiment

[Benchmark run 44033934420](https://github.com/ryandens/agents/actions/runs/44033934420)
ran the native CI aggregate twice on each of two GitHub-hosted `ubuntu-latest`
runners at PR merge revision `b589b21`. Both runners had four vCPUs and about
16 GiB RAM. The CLI and engine used Dagger `v1.0.0-beta.25`, and the repository
selected Python SDK `v1.8.0`. The workflow prepared the CLI before measurement
and retained the default aggregate concurrency of two. Each invocation enforced
its saved status. All four passed the same 20 checks and both report exports.

| Runner | Docker engine after first invocation | First | Repeat | Reduction |
| --- | --- | --- | --- | --- |
| 1 | `8efa3b39255b` | [263.0s](https://dagger.cloud/ryandens/traces/fa1e23a6fc5d84d0b5a60513a4cfb845) | [24.8s](https://dagger.cloud/ryandens/traces/723c4961ffe89fd3b70fe641d0f6a179) | 91% |
| 2 | `7f7084ee67ef` | [295.9s](https://dagger.cloud/ryandens/traces/9008d1f5de6d0284055d34140b66886c) | [30.8s](https://dagger.cloud/ryandens/traces/3b65ca93089edafbfa10c37d59138a64) | 90% |

Times are from the Actions step start to the Dagger trace link in the log.
Both runners started without a running Dagger container and showed a distinct
local engine container before the repeat. The workflow left each engine running
and did not clear any caches.

The backend test and ARM64 image checks took 57–68s and 72–80s respectively on
the first invocations. Both rounded to 0.0s on the repeats. OpenGrep still took
18.7–23.2s on the repeats, and the Python Socket check took 0.9–1.0s in all four
invocations. The repeated sessions retained fresh policy enforcement.

The timing difference shows substantial reuse within a runner. Both independent
runners paid the first-run cost, so neither showed warm-run performance on its
first invocation. The jobs overlapped, so this experiment did not test whether a
later job can import cache entries populated by a completed job. The console logs
did not identify operation-level cache hits, backend configuration, or mutable
cache-volume reuse, and the linked Cloud spans could not be inspected. A sequential
same-revision run with operation-level trace evidence is still needed to establish
which cache data can persist across jobs.
