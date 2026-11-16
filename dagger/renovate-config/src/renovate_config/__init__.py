from dagger_clients.core import Container, Directory, core

from dagger import function, object_type

# renovate: datasource=docker depName=ghcr.io/renovatebot/renovate
IMAGE = "ghcr.io/renovatebot/renovate:44.246.2@sha256:18a3700d2d1535d56375cde676d59d5fb0826aae22c5b9def2d8eae7b2086ca6"


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
