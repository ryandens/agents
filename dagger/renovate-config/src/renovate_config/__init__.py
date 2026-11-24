from dagger_clients.core import Container, Directory, core

from dagger import function, object_type

# renovate: datasource=docker depName=ghcr.io/renovatebot/renovate
IMAGE = "ghcr.io/renovatebot/renovate:44.259.0@sha256:63bec0c6e61553bf30c623f4ebe7e6ae087118c050288f9d47f9a6ab0f8f9bfe"


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
