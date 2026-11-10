# Renovate config validator

An independent Python Dagger module using the official Renovate image, pinned
by version and digest.
It runs only `renovate-config-validator`; it never runs the dependency-update bot.
No repository write credentials or host npm installation is required.

`check(source, config_file="renovate.json", strict=False, container=None)` validates
the selected source-relative file with `--no-global`, matching repository-config
validation. Missing files, warnings and validation errors fail. Strict mode also
rejects configuration requiring migration. A supplied container must provide
`renovate-config-validator` on PATH for custom runtimes or contract fixtures.

```python
from dagger_clients.renovate_config import renovate_config

await renovate_config().check(source)
```

The app exposes this as the `renovate-config` check in `dagger check` and
`just check`, including changes outside Renovate's own configuration. The generated
SDK and core client are included for later Daggerverse extraction. Add its Python
scope to the destination workspace, choose a license and tag releases independently.
