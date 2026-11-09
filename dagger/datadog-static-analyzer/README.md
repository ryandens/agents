# Datadog Static Analyzer

An independent Python Dagger module for Datadog's credential-free scanner. The
container image is pinned by version and digest; the caller controls Git selection,
GitHub uploads and organization integrations.

## API

`scan(source, fail_on="error,warning", container=None)` returns a `ScanResult`:

- `sarif()` returns the report even when findings fail policy.
- `exit_code()` returns the original analyzer status.
- `logs()` returns stdout and stderr.
- `assert_passed()` validates the report and fails on a nonzero analyzer status.

The source directory should include `code-security.datadog.yaml` and applicable
ignore files. The analyzer runs from `/src`; tested reports contain repository-relative
artifact paths. An optional caller container must expose `datadog-static-analyzer`
on PATH. Scanner crashes and missing/malformed reports fail; no empty report is
fabricated to conceal them.

```python
from dagger_clients.datadog_static_analyzer import datadog_static_analyzer

result = datadog_static_analyzer().scan(source)
report = result.sarif()  # Export or publish before enforcing policy.
await result.assert_passed()
```

## Repository integration

`just datadog-check` exports to `reports/datadog`, prints logs, then enforces status.
CI uploads the SARIF before enforcing that status. It prepares added/modified PR
files with their original paths; rules or ignore changes force a full scan. Main
always gets a full scan. This integration does not require Datadog credentials or
use its account-dependent diff-aware mode.

`module-contracts` exercises clean output, policy failure with preserved SARIF,
and scanner failure without a report using `tests/fake-analyzer.sh`.

This directory includes its generated SDK and client and can be extracted into a
Daggerverse repository. Tested with Dagger beta.25 and Python SDK v1.7.0 using the native Python runtime. Choose a license and an independent release tag before publishing.
