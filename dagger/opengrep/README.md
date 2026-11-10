# OpenGrep

An independent Python Dagger module for checksum-verified OpenGrep. The default
runtime uses its Linux x86-64 release on `linux/amd64`, including on ARM hosts.
No hosted service or API token is required. The version and checksum update together
through Renovate. Registry rules are refreshed for each Dagger session; report fields share one scan.

`scan(source, config="p/default", strict=False, container=None)` returns a `ScanResult`:

- `sarif()` returns the original report, including explicit suppressions.
- `logs()` and `exit_code()` retain the scanner's output and status.
- `policy_exit_code()` honors explicit source suppressions while preserving errors.
- `assert_passed()` rejects active findings, scanner errors and invalid/missing reports.

The source should include `.semgrepignore` and applicable ignore files. `config`
may select a registry ruleset or a source-relative rule file. A supplied container
must expose `opengrep` on PATH. Scans use `--error`; active findings fail policy. Parser diagnostics remain in the
report and logs, matching the prior CI behavior. Set `strict=True` to fail on parser
warnings too. A finding status caused entirely by explicitly suppressed report
entries passes policy; scanner errors always fail. Raw exit status remains available.
Reports remain exportable before enforcing policy.

```python
from dagger_clients.opengrep import opengrep

result = opengrep().scan(source)
sarif = result.sarif()
await result.assert_passed()
```

Git selection and publication belong to the caller. This repository uses
`scripts/prepare_opengrep_scan.py` for path-preserving changed-file PR scans; ignore
changes and main pushes receive a full scan. The app removes explicitly suppressed
results only from the GitHub upload, exports raw status as `raw-exit-code`, and
exports the policy status as `exit-code`. Logs retain the scanner diagnostics.
`just opengrep-check` runs the same module locally. Fixtures cover findings, scanner
errors, clean results and crashes without a report.

The generated SDK and core client are included for later Daggerverse extraction.
Add the Python scope to the destination workspace, choose a license and tag releases
independently. This module has no application or GitHub dependency.
