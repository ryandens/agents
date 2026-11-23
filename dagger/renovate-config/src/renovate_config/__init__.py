from dagger_clients.core import Container, Directory, core

from dagger import function, object_type

# renovate: datasource=docker depName=ghcr.io/renovatebot/renovate
IMAGE = "ghcr.io/renovatebot/renovate:44.258.3@sha256:47081d75a438c1234e5b078ca934ff6418a1d7ef284ac81e9592e67974b67fd9"


@object_type
class RenovateConfig:
    """Validate repository Renovate configuration without running the update bot."""

    @function
    async def check(
        self,
        source: Directory,
        config_file: str = "renovate.json",
        strict: bool = False,
        container: Container | None = None,
    ) -> None:
        """Validate a source-relative config as repository configuration.

        Strict mode also rejects configuration requiring migration. A supplied
        container must provide renovate-config-validator on PATH.
        """
        if config_file.startswith(("/", "-")) or ".." in config_file.split("/"):
            raise ValueError("config_file must be a source-relative file path")
        await source.file(config_file).contents()
        ctr = container if container is not None else core().container().from_(IMAGE)
        await (
            ctr.without_entrypoint()
            .with_workdir("/src")
            .with_directory("/src", source)
            .with_exec(
                [
                    "renovate-config-validator",
                    "--no-global",
                    *(["--strict"] if strict else []),
                    config_file,
                ]
            )
            .sync()
        )
