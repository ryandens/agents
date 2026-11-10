# This module requires Python >=3.14; pre-3.7 compatibility is not supported.
# nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from importlib.resources import files
from typing import Annotated

from dagger_clients.core import Container, File, core

from dagger import Doc, function, object_type

# renovate: datasource=github-releases depName=SocketDev/sfw-free
VERSION = "v1.16.0"
RELEASES = {"amd64": "x86_64", "arm64": "arm64"}
CHECKSUMS = {
    name: f"sha256:{checksum}"
    for checksum, name in (
        line.split()
        for line in files(__package__)
        .joinpath("checksums.sha256")
        .read_text()
        .splitlines()
        if line and not line.startswith("#")
    )
}


@object_type
class SocketFirewall:
    """Protect package-manager downloads inside a caller's Linux container."""

    @function
    async def install(
        self,
        container: Container,
        binary: Annotated[
            File | None,
            Doc("Optional trusted sfw binary for custom releases or test fixtures."),
        ] = None,
    ) -> Container:
        """Add a checksum-verified sfw binary; preserve the caller's image and settings.

        The default binaries target glibc Linux. The caller supplies CA certificates
        and runtime libraries. No global proxy or package-manager config is changed.
        """
        if binary is None:
            platform = str(await container.platform()).split("/")
            if (
                len(platform) < 2
                or platform[0] != "linux"
                or platform[1] not in RELEASES
            ):
                raise ValueError(f"unsupported Socket platform: {'/'.join(platform)}")
            arch = RELEASES[platform[1]]
            binary = core().http(
                f"https://github.com/SocketDev/sfw-free/releases/download/{VERSION}/sfw-free-linux-{arch}",
                checksum=CHECKSUMS[f"sfw-free-linux-{arch}"],
            )
        return container.with_file("/usr/local/bin/sfw", binary, permissions=0o755)

    @function
    async def run(
        self,
        container: Container,
        args: list[str],
        binary: File | None = None,
    ) -> Container:
        """Execute an argument vector through Socket, failing on any nonzero exit.

        The caller controls dependency cache mounts and freshness. Use an empty
        package cache and a distinct execution key for a fresh policy check.
        """
        if not args:
            raise ValueError("a package-manager command is required")
        return (await self.install(container, binary)).with_exec(
            ["/usr/local/bin/sfw", *args]
        )
