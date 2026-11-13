import json

from dagger_clients.core import Container, Directory, File, ReturnType, core

from dagger import field, function, object_type

# renovate: datasource=docker depName=ghcr.io/datadog/datadog-static-analyzer
IMAGE = "ghcr.io/datadog/datadog-static-analyzer:0.9.13@sha256:61aa4e65bf7b1407fb4288da163b7310013cd14f3ad3c603d8a3a82982f4f416"


@object_type
class ScanResult:
    """A completed scan whose report remains available when policy fails."""

    process: Container = field()

    @function
    def sarif(self) -> File:
        """SARIF report; fails clearly if the analyzer did not produce it."""
        return self.process.file("/reports/results.sarif")

    @function
    async def exit_code(self) -> int:
        return await self.process.exit_code()

    @function
    async def logs(self) -> str:
        return await self.process.stdout() + await self.process.stderr()

    @function
    async def assert_passed(self) -> None:
        """Fail on scanner errors, invalid reports or policy violations."""
        report = json.loads(await self.sarif().contents())
        if report.get("version") != "2.1.0" or not isinstance(report.get("runs"), list):
            raise ValueError("analyzer did not produce a SARIF 2.1.0 report")
        status = await self.exit_code()
        if status:
            raise RuntimeError(
                f"Datadog scan failed (exit {status})\n{await self.logs()}"
            )


@object_type
class DatadogStaticAnalyzer:
    """Run Datadog's credential-free analyzer and expose reports separately from policy."""

    @function
    def scan(
        self,
        source: Directory,
        fail_on: str = "error,warning",
        container: Container | None = None,
    ) -> ScanResult:
        """Scan source, honoring its code-security.datadog.yaml and ignore files.

        A caller-supplied container must provide datadog-static-analyzer on PATH.
        Git selection and report upload belong to the caller.
        """
        ctr = container if container is not None else core().container().from_(IMAGE)
        process = (
            ctr.without_entrypoint()
            .with_workdir("/src")
            .with_directory("/src", source)
            .with_new_file("/reports/.keep", "")
            .with_exec(
                [
                    "datadog-static-analyzer",
                    "-i",
                    "/src",
                    "-o",
                    "/reports/results.sarif",
                    "-f",
                    "sarif",
                    "--print-violations",
                    "--fail-on-any-violation",
                    fail_on,
                ],
                expect=ReturnType.ANY,
            )
        )
        return ScanResult(process=process)
