import json
import uuid

from dagger_clients.core import Container, Directory, File, Platform, ReturnType, core

from dagger import field, function, object_type

# renovate: datasource=custom.opengrep-releases depName=opengrep/opengrep
VERSION = "v1.33.1"
SHA256 = "sha256:46e8133cc490f9f50518061590ce2f6be5a08afaeda034471c0ceda4b3899808"
# renovate: datasource=docker depName=debian
BASE_IMAGE = "debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc"


@object_type
class ScanResult:
    """OpenGrep results remain available independently of policy enforcement."""

    process: Container = field()

    @function
    def sarif(self) -> File:
        """Return the unmodified SARIF, including explicit source suppressions."""
        return self.process.file("/reports/results.sarif")

    @function
    async def exit_code(self) -> int:
        return await self.process.exit_code()

    @function
    async def logs(self) -> str:
        return await self.process.stdout() + await self.process.stderr()

    @function
    async def policy_exit_code(self) -> int:
        """Keep tool errors fatal and honor explicit SARIF source suppressions."""
        report = json.loads(await self.sarif().contents())
        if report.get("version") != "2.1.0" or not isinstance(report.get("runs"), list):
            raise ValueError("OpenGrep did not produce a SARIF 2.1.0 report")
        status = await self.exit_code()
        if status not in (0, 1):
            return status
        results = [
            result for run in report["runs"] for result in run.get("results", [])
        ]
        if any(not result.get("suppressions") for result in results):
            return 1
        # A finding exit with no report entries cannot be explained by suppressions.
        return 1 if status == 1 and not results else 0

    @function
    async def assert_passed(self) -> None:
        """Reject active findings, scanner errors and malformed or missing SARIF."""
        status = await self.policy_exit_code()
        if status:
            raise RuntimeError(
                f"OpenGrep scan failed (exit {status})\n{await self.logs()}"
            )


@object_type
class Opengrep:
    """Run checksum-verified OpenGrep without a hosted service or API token."""

    @function(cache="session")
    def scan(
        self,
        source: Directory,
        config: str = "p/default",
        strict: bool = False,
        container: Container | None = None,
    ) -> ScanResult:
        """Scan a source directory, honoring its .semgrepignore and source suppressions.

        Config may be a registry ruleset or a rules file inside the source.
        A supplied container must provide opengrep on PATH. Source selection and
        report publication belong to the caller.
        """
        if container is None:
            ctr = (
                core()
                .container(platform=Platform("linux/amd64"))
                .from_(BASE_IMAGE)
                .with_exec(["apt-get", "update"])
                .with_exec(
                    [
                        "apt-get",
                        "install",
                        "-y",
                        "--no-install-recommends",
                        "ca-certificates",
                        "git",
                        "libgomp1",
                        "libstdc++6",
                        "zlib1g",
                    ]
                )
                .with_file(
                    "/usr/local/bin/opengrep",
                    core().http(
                        f"https://github.com/opengrep/opengrep/releases/download/{VERSION}/opengrep_manylinux_x86"
                    ),
                    permissions=0o755,
                )
                .with_new_file(
                    "/usr/local/share/opengrep/checksums.sha256",
                    f"{SHA256.removeprefix('sha256:')}  /usr/local/bin/opengrep\n",
                )
                .with_exec(
                    [
                        "sha256sum",
                        "--check",
                        "--strict",
                        "/usr/local/share/opengrep/checksums.sha256",
                    ]
                )
            )
        else:
            ctr = container
        process = (
            ctr.without_entrypoint()
            .with_workdir("/src")
            .with_directory("/src", source)
            .with_env_variable("OPENGREP_SCAN_RUN", uuid.uuid4().hex)
            .with_new_file("/reports/.keep", "")
            .with_exec(
                [
                    "opengrep",
                    "scan",
                    "--error",
                    *(["--strict"] if strict else []),
                    "--config",
                    config,
                    "--sarif-output=/reports/results.sarif",
                    ".",
                ],
                expect=ReturnType.ANY,
            )
        )
        return ScanResult(process=process)
