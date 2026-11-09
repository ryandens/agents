# Dagger application checks

The third adoption layer runs backend, CLI and frontend checks in one Dagger CI job.
The separate CLI shadow workflow is removed.
The job runs `scripts/dagger check -j 2 --progress report`, which discovers all
checks in this layer, including generated-client staleness, and reports each result.

Backend tests bind a disposable Postgres service through TEST_DATABASE_URL; fresh Socket
checks cover uv and pnpm downloads. Development installs and hot reload remain native.

Use `just backend-check`, `just cli-check`, `just frontend-check` or `just check`.
`just dagger-check` also checks handwritten pipeline code and generated-client
staleness. `just dagger-generate` updates the vendored clients after API changes.
The repo wrapper selects the pinned CLI/engine and isolates ignored local state.
The app constructor captures explicit content-addressed source inputs for caching.

Datadog, Docker image builds, smoke tests and releases still use their original
workflows and recipes in this layer. No deployment behavior changes.

## Merge order

1. Socket module and optional CLI checks.
2. Backend and CLI checks.
3. Frontend checks (this layer).
4. Datadog reporting and image/smoke checks.
5. Release verification and publishing.

Each PR targets its predecessor. Merge from the bottom and retarget the next PR
to main after its dependency lands. Deployment remains `just deploy`.
