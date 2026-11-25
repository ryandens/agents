# Dagger CI baseline and cache investigation

Baseline measured November 16, 2026, with follow-up benchmarks on November 17
(America/Los_Angeles).
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
which cache data can persist across jobs. The sequential experiment below tests
execution results and mutable volumes directly.

## Cache reuse between sequential runners

[Benchmark run 44243697560](https://github.com/ryandens/agents/actions/runs/44243697560)
ran the same aggregate at merge revision `cd37db7` on two independent Ubuntu
26.04 runners. The second job waited for the first to complete. Both passed
the same 20 checks and both report exports with the existing Cloud token
configuration. Each started a distinct local Dagger beta.25 Docker container
with a Docker volume mounted at `/var/lib/dagger`.

| Job | Engine | Checks/report step | Whole job |
| --- | --- | --- | --- |
| Seed | `a45f56b3e226` | [279s](https://dagger.cloud/ryandens/traces/87a427596f6b35df7e09fd1409a9ef24) | 311s |
| Observe | `65cf79f63252` | [296s](https://dagger.cloud/ryandens/traces/2126e1edda9b9af68d6272dab06b1bfa) | 331s |

After the aggregate in each job, a direct engine query generated a random UUID
using the same run-specific cache key. Repeating the query in a new session on
the seed runner returned the original UUID and logged `withExec CACHED`. The
observe runner logged a fresh execution and returned a different UUID.
[Seed repeat trace](https://dagger.cloud/ryandens/traces/e7a648fd3f6208235d93819847697c8d),
[observe execution trace](https://dagger.cloud/ryandens/traces/fe209ae7ab4230b0f2dbf9bf70e4e6f1).

A separate probe wrote the seed UUID into a named cache volume and recovered it
in a new local session. The observe job used the same volume key and a distinct
execution environment to force a fresh read. The marker was absent.
[Seed read trace](https://dagger.cloud/ryandens/traces/a9cf74cbad02abbbad6e5be6f30e0d7f),
[observe read trace](https://dagger.cloud/ryandens/traces/5571b64712f6acaa16ed5b0f0dd5c1d9).

The existing GitHub runner configuration did not carry either probed cache entry
between jobs. These results cover one execution operation and one mutable volume.
They leave base-image transfer and other cache classes unmeasured.

## Aggregate concurrency on fresh runners

[Benchmark run 44242340883](https://github.com/ryandens/agents/actions/runs/44242340883)
tested three independent jobs per setting at merge revision `296073f`. Each job
used a fresh Ubuntu 26.04 x86-64 runner with four vCPUs, about 16 GiB RAM and a
separate local Dagger beta.25 engine. The CLI was prepared before measurement.
The aggregate command used `ci --parallel N export` and enforced the saved result.
All six invocations passed the same 20 checks and both report exports.

| Parallel | Sample | Aggregate | Whole job | ARM64 image check | Mean host CPU busy |
| --- | --- | --- | --- | --- | --- |
| 2 | 1 | [299.83s](https://dagger.cloud/ryandens/traces/902881eb2c12374ffcaa815322ae9417) | 336s | 76s | 54% |
| 2 | 2 | [230.57s](https://dagger.cloud/ryandens/traces/74c9da2e040c5a55bc51f9692890885d) | 256s | 58.6s | 56% |
| 2 | 3 | [266.83s](https://dagger.cloud/ryandens/traces/730f46eab5d7e1b61a125ef733721efb) | 297s | 74s | 61% |
| 4 | 1 | [255.46s](https://dagger.cloud/ryandens/traces/741f25b3ac57d70082f7d513fc3410a2) | 293s | 116s | 73% |
| 4 | 2 | [271.27s](https://dagger.cloud/ryandens/traces/ea4e0da7fbffc127f67babf1a698cf19) | 300s | 150s | 91% |
| 4 | 3 | [208.17s](https://dagger.cloud/ryandens/traces/b0f082dcb121efb59a90f997521f7750) | 233s | 97s | 74% |

The aggregate median fell from 266.83s to 255.46s (11.37s, or 4.3%). The
slowest sample fell from 299.83s to 271.27s. Whole-job medians were 297s and
293s. Linux memory-pressure totals rose by less than 0.65s per job and
one-second `vmstat` samples showed no swap-ins. CPU figures sum user and
system time from those samples. The ARM64 check duration
includes shared work, so it cannot isolate time spent in emulation.

Keep the default at two. The aggregate ranges overlap substantially, while
all three runs at four increased CPU utilization and the ARM64 check took
longer than in any run at two. The measured whole-job median gain was four
seconds.
