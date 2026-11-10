from dagger_clients.core import Container, Directory, core

from dagger import function, object_type

# renovate: datasource=docker depName=rhysd/actionlint
IMAGE = "rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"


@object_type
class Actionlint:
    """Check GitHub Actions workflows with actionlint, ShellCheck and pyflakes."""

    @function
    async def check(
        self, source: Directory, container: Container | None = None
    ) -> None:
        """Validate workflows and repository actionlint configuration.

        A supplied container must provide actionlint on PATH.
        """
        paths = sorted(
            await source.glob(".github/workflows/*.yml")
            + await source.glob(".github/workflows/*.yaml")
        )
        if not paths:
            raise ValueError("no GitHub Actions workflows found")
        args = ["actionlint", "-color"]
        for config in (".github/actionlint.yaml", ".github/actionlint.yml"):
            if await source.glob(config):
                args.extend(["-config-file", config])
                break
        ctr = container if container is not None else core().container().from_(IMAGE)
        await (
            ctr.without_entrypoint()
            .with_workdir("/repo")
            .with_directory("/repo", source)
            .with_exec([*args, *paths])
            .sync()
        )
