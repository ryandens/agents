# Actionlint

An independent Python Dagger module using the official versioned Actionlint image.
The image includes ShellCheck and pyflakes and is pinned by version and digest.

`check(source, container=None)` validates every `.github/workflows/*.yml` and
`*.yaml` file and honors `.github/actionlint.yaml` or `.github/actionlint.yml`.
Pass the repository root as `source`; no Git metadata or GitHub credentials are
needed. Missing workflows and lint failures fail the call. A supplied container
must expose `actionlint` on PATH, allowing deterministic failure-contract fixtures.

```python
from dagger_clients.actionlint import actionlint

await actionlint().check(source)
```

The app exposes this as the `actionlint` check in the same `dagger check` suite
used locally and in CI. Generated SDK/client files travel with this directory when
extracting it into a Daggerverse; add its Python scope to the destination workspace,
choose a license and tag module releases independently.
