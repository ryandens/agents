# Incremental Dagger adoption

This first step adds a reusable Socket Firewall module and CLI lint, format and
test checks alongside existing CI. Existing `just check`, application checks,
Datadog, Docker builds and release publishing retain their current behavior.
The separate Dagger CLI workflow is observational; it is not added to branch protection.

Install Docker, Dagger and Python 3, then run `just dagger-check`. The repo wrapper
selects the pinned CLI/engine. `just dagger-generate` refreshes module clients.
The pipeline captures explicit source inputs and isolates local ignored state.
The SDK/client copies are generated, checked for staleness and excluded from source scans.

The checks exercise CLI tests with synthetic Safari data, a fresh Socket-protected
uv install, blocked-install contracts and pipeline linting. No macOS privacy grant
or production credentials are required. Existing native CI is the comparison baseline.

## Merge order

1. Add Socket and optional CLI checks (this step).
2. Promote application checks: backend with Postgres, CLI and frontend.
3. Add Datadog report handling and production image/smoke checks.
4. Move tagged-release verification and publication to Dagger.

Each later PR targets the preceding branch. Merge in order, retargeting the next
PR to main after its dependency lands. Deployment continues to use `just deploy`.
The full migration is preserved on `codex/dagger-full-backup` while this stack is reviewed.
