import re
import uuid
from typing import Self

from dagger_clients.actionlint import actionlint
from dagger_clients.core import (
    Container,
    Directory,
    Platform,
    Secret,
    Service,
    Workspace,
    core,
)
from dagger_clients.datadog_static_analyzer import datadog_static_analyzer
from dagger_clients.opengrep import opengrep
from dagger_clients.socket_firewall import socket_firewall

from dagger import ExecError, QueryError, check, field, function, object_type

_EXCLUDE = [
    "**/.venv/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.env",
    "**/.env.*",
    "backend/static/**",
    "backend/data/**",
    "frontend/.next/**",
    "frontend/out/**",
    "frontend/coverage/**",
]


_MANIFESTS = [
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "backend/pyproject.toml",
    "cli/pyproject.toml",
]


def _source(source: Directory, include: list[str]) -> Directory:
    return (
        source.filter(include=include, exclude=_EXCLUDE).as_workspace().directory("/")
    )


async def _image(source: Directory, stage: str) -> str:
    dockerfile = await source.file("backend/Dockerfile").contents()
    match = re.search(
        rf"^FROM (?:--platform=\S+ )?(\S+) AS {stage}$", dockerfile, re.MULTILINE
    )
    if match is None:
        raise ValueError(f"missing Dockerfile stage: {stage}")
    return match[1]


async def _uv_image(source: Directory) -> str:
    dockerfile = await source.file("backend/Dockerfile").contents()
    match = re.search(r"COPY --from=(ghcr.io/astral-sh/uv:\S+) /uv ", dockerfile)
    if match is None:
        raise ValueError("missing pinned uv image in backend/Dockerfile")
    return match[1]


async def _python_base(source: Directory) -> Container:
    version = (await source.file(".python-version").contents()).strip()
    return (
        core()
        .container()
        .from_(f"python:{version}-slim")
        .with_file(
            "/usr/local/bin/uv",
            core().container().from_(await _uv_image(source)).file("/uv"),
        )
        .with_env_variable("UV_PYTHON_DOWNLOADS", "never")
        .with_env_variable("UV_LINK_MODE", "copy")
        .with_workdir("/src")
        .with_directory("/src", _source(source, _MANIFESTS))
    )


async def _python(source: Directory, package: str, *, fresh: bool = False) -> Container:
    ctr = await _python_base(source)
    if fresh:
        ctr = ctr.with_env_variable(
            "SOCKET_CHECK_RUN", uuid.uuid4().hex
        ).with_env_variable("UV_NO_CACHE", "1")
    else:
        ctr = ctr.with_mounted_cache(
            "/root/.cache/uv", core().cache_volume("agents-uv")
        )
    args = ["uv", "sync", "--locked", "--dev", "--package", package]
    # Install third-party dependencies before copying source for stable dependency layers.
    ctr = socket_firewall().run(ctr, [*args, "--no-install-workspace"])
    paths = (
        ["cli/**"]
        if package == "safari-history-export"
        else ["backend/**", "scripts/**"]
    )
    ctr = ctr.with_directory("/src", _source(source, paths))
    return socket_firewall().run(ctr, args)


async def _frontend(source: Directory, *, fresh: bool = False) -> Container:
    ctr = (
        core()
        .container()
        .from_(await _image(source, "frontend"))
        .with_directory(
            "/opt/pnpm",
            core()
            .container()
            .from_(await _image(source, "pnpm"))
            .directory("/opt/pnpm"),
        )
        .with_env_variable("PATH", "/opt/pnpm:$PATH", expand=True)
        .with_env_variable("CI", "true")
        .with_workdir("/src/frontend")
        .with_directory(
            "/src",
            _source(
                source,
                [
                    "frontend/package.json",
                    "frontend/pnpm-lock.yaml",
                    "frontend/pnpm-workspace.yaml",
                ],
            ),
        )
    )
    if fresh:
        ctr = ctr.with_env_variable("SOCKET_CHECK_RUN", uuid.uuid4().hex)
    else:
        ctr = ctr.with_mounted_cache("/pnpm/store", core().cache_volume("agents-pnpm"))
    ctr = socket_firewall().run(
        ctr, ["pnpm", "install", "--frozen-lockfile", "--store-dir", "/pnpm/store"]
    )
    return ctr.with_directory("/src", _source(source, ["frontend/**"]))


def _run_python(ctr: Container, package: str, args: list[str]) -> Container:
    return ctr.with_exec(["uv", "run", "--no-sync", "--package", package, *args])


@object_type
class AgentsCi:
    """Portable application checks, reports, images and release publishing."""

    source: Directory = field()

    @classmethod
    async def create(cls, ws: Workspace) -> Self:
        source = (
            ws.directory(
                "/",
                include=[
                    "backend/**",
                    "cli/**",
                    "frontend/**",
                    "scripts/**",
                    ".github/**",
                    "infrastructure/*.tf",
                    ".dagger/src/**",
                    "dagger/*/src/**",
                    "dagger/*/tests/**",
                    "pyproject.toml",
                    "uv.lock",
                    ".python-version",
                    ".dockerignore",
                    ".semgrepignore",
                    "code-security.datadog.yaml",
                    "renovate.json",
                    "ruff.toml",
                    "**/.gitignore",
                    "**/.gitattributes",
                ],
                exclude=_EXCLUDE,
                gitignore=True,
            )
            .as_workspace()
            .directory("/")
        )
        return cls(source=source)

    @check
    @function
    async def actionlint(self) -> None:
        """Validate all GitHub Actions workflows and their embedded scripts."""
        await actionlint().check(_source(self.source, [".github/**"]))

    @check
    @function
    async def module_contracts(self) -> None:
        """Blocked installs and failed scans must preserve failure and report semantics."""
        base = core().container().from_("alpine:3.22").with_workdir("/work")
        fake_socket = _source(self.source, ["dagger/socket-firewall/tests/**"]).file(
            "dagger/socket-firewall/tests/fake-sfw.sh"
        )
        output = socket_firewall().run(
            base.with_env_variable("FIXTURE_VALUE", "a value with spaces; $literal"),
            ["sh", "-c", 'printf "%s" "$FIXTURE_VALUE" > artifact'],
            binary=fake_socket,
        )
        assert (
            await output.file("/work/artifact").contents()
            == "a value with spaces; $literal"
        )
        try:
            await (
                socket_firewall()
                .run(
                    base.with_env_variable("SOCKET_FIXTURE_BLOCK", "1"),
                    ["true"],
                    binary=fake_socket,
                )
                .sync()
            )
        except (QueryError, ExecError) as error:
            if "29" not in str(error):
                raise
        else:
            raise AssertionError("blocked package installation succeeded")

        fake_analyzer = _source(
            self.source, ["dagger/datadog-static-analyzer/tests/**"]
        ).file("dagger/datadog-static-analyzer/tests/fake-analyzer.sh")
        analyzer = base.with_file(
            "/usr/local/bin/datadog-static-analyzer", fake_analyzer, permissions=0o755
        )
        source = core().directory().with_new_file("example.py", "print('fixture')\n")
        clean = datadog_static_analyzer().scan(source, container=analyzer)
        await clean.assert_passed()
        failed = datadog_static_analyzer().scan(
            source, container=analyzer.with_env_variable("SCAN_FIXTURE_EXIT", "1")
        )
        assert '"version":"2.1.0"' in await failed.sarif().contents()
        assert await failed.exit_code() == 1
        try:
            await failed.assert_passed()
        except (QueryError, ExecError) as error:
            # Errors crossing a Python module boundary are reported as its exec's
            # status (2); the result object's original analyzer status remains 1.
            if "exit" not in str(error):
                raise
        else:
            raise AssertionError("scan policy failure was swallowed")
        crashed = datadog_static_analyzer().scan(
            source, container=analyzer.with_env_variable("SCAN_FIXTURE_CRASH", "1")
        )
        assert await crashed.exit_code() == 2
        try:
            await crashed.sarif().contents()
        except QueryError as error:
            assert "results.sarif" in str(error)
        else:
            raise AssertionError("scanner crash fabricated a report")

        lint_source = (
            core()
            .directory()
            .with_new_file(
                ".github/workflows/check.yml", "name: fixture\non: push\njobs: {}\n"
            )
        )
        fake_linter = self.source.file("dagger/actionlint/tests/fake-actionlint.sh")
        linter = base.with_file(
            "/usr/local/bin/actionlint", fake_linter, permissions=0o755
        )
        await actionlint().check(lint_source, container=linter)
        try:
            await actionlint().check(
                lint_source,
                container=linter.with_env_variable("LINT_FIXTURE_EXIT", "1"),
            )
        except (QueryError, ExecError):
            pass
        else:
            raise AssertionError("invalid workflow passed actionlint")

        fake_opengrep = self.source.file("dagger/opengrep/tests/fake-opengrep.sh")
        scanner = base.with_file(
            "/usr/local/bin/opengrep", fake_opengrep, permissions=0o755
        )
        await opengrep().scan(source, container=scanner).assert_passed()
        suppressed_scan = opengrep().scan(
            source, container=scanner.with_env_variable("SCAN_FIXTURE_SUPPRESSED", "1")
        )
        assert await suppressed_scan.exit_code() == 1
        assert await suppressed_scan.policy_exit_code() == 0
        await suppressed_scan.assert_passed()
        suppressed_error = opengrep().scan(
            source,
            container=scanner.with_env_variable(
                "SCAN_FIXTURE_SUPPRESSED", "1"
            ).with_env_variable("SCAN_FIXTURE_EXIT", "2"),
        )
        assert await suppressed_error.policy_exit_code() == 2
        for status in (1, 2):
            failed_scan = opengrep().scan(
                source,
                container=scanner.with_env_variable("SCAN_FIXTURE_EXIT", str(status)),
            )
            assert await failed_scan.exit_code() == status
            assert '"version":"2.1.0"' in await failed_scan.sarif().contents()
            try:
                await failed_scan.assert_passed()
            except (QueryError, ExecError):
                pass
            else:
                raise AssertionError(f"OpenGrep exit {status} was swallowed")
        crashed_scan = opengrep().scan(
            source, container=scanner.with_env_variable("SCAN_FIXTURE_CRASH", "1")
        )
        assert await crashed_scan.exit_code() == 2
        try:
            await crashed_scan.sarif().contents()
        except QueryError:
            pass
        else:
            raise AssertionError("OpenGrep crash fabricated a report")

    @check
    @function
    async def socket_pins(self) -> None:
        """Production Dockerfile and reusable module must use identical verified tools."""
        source = _source(
            self.source,
            [
                "backend/Dockerfile",
                "dagger/socket-firewall/src/socket_firewall/__init__.py",
                "dagger/socket-firewall/src/socket_firewall/checksums.sha256",
            ],
        )
        dockerfile = await source.file("backend/Dockerfile").contents()
        module = await source.file(
            "dagger/socket-firewall/src/socket_firewall/__init__.py"
        ).contents()
        version = re.search(r'VERSION = "([^"]+)"', module)
        assert version is not None
        assert dockerfile.count(f"/download/{version[1]}/") == 2
        checksums = await source.file(
            "dagger/socket-firewall/src/socket_firewall/checksums.sha256"
        ).contents()
        assert checksums.count(f"# version={version[1]} ") == 2

    @function
    def postgres(self, database: str = "agents") -> Service:
        """A disposable database matching the application's PostgreSQL major."""
        return (
            core()
            .container()
            .from_("postgres:17-alpine")
            .with_env_variable("POSTGRES_USER", "agents")
            .with_env_variable("POSTGRES_PASSWORD", "agents")
            .with_env_variable("POSTGRES_DB", database)
            .with_exposed_port(5432)
            .as_service(use_entrypoint=True)
        )

    @check
    @function
    async def backend_lint(self) -> None:
        await _run_python(
            await _python(self.source, "agents"),
            "agents",
            ["ruff", "check", "backend", "scripts"],
        ).stdout()

    @check
    @function
    async def backend_format(self) -> None:
        await _run_python(
            await _python(self.source, "agents"),
            "agents",
            ["ruff", "format", "--check", "backend", "scripts"],
        ).stdout()

    @check
    @function
    async def backend_test(self) -> None:
        ctr = (
            (await _python(self.source, "agents"))
            .with_service_binding("postgres", self.postgres())
            .with_env_variable(
                "TEST_DATABASE_URL",
                "postgresql://agents:agents@postgres:5432/agents",
            )
        )
        await _run_python(ctr, "agents", ["pytest", "backend"]).stdout()

    @check
    @function
    async def cli_lint(self) -> None:
        await _run_python(
            await _python(self.source, "safari-history-export"),
            "safari-history-export",
            ["ruff", "check", "cli"],
        ).stdout()

    @check
    @function
    async def cli_format(self) -> None:
        await _run_python(
            await _python(self.source, "safari-history-export"),
            "safari-history-export",
            ["ruff", "format", "--check", "cli"],
        ).stdout()

    @check
    @function
    async def cli_test(self) -> None:
        await _run_python(
            await _python(self.source, "safari-history-export"),
            "safari-history-export",
            ["pytest", "cli"],
        ).stdout()

    @check
    @function
    async def frontend_lint(self) -> None:
        await (await _frontend(self.source)).with_exec(["pnpm", "run", "lint"]).stdout()

    @check
    @function
    async def frontend_test(self) -> None:
        await (await _frontend(self.source)).with_exec(["pnpm", "run", "test"]).stdout()

    @function
    async def frontend_dist(self) -> Directory:
        """The static export consumed by the production image."""
        return (
            (await _frontend(self.source))
            .with_exec(["pnpm", "run", "build"])
            .directory("/src/frontend/out")
        )

    @check
    @function
    async def frontend_build(self) -> None:
        await (await self.frontend_dist()).sync()

    @check
    @function(cache="never")
    async def socket_python(self) -> None:
        """Recheck Python downloads with an empty cache and a unique execution key."""
        await (await _python(self.source, "agents", fresh=True)).stdout()

    @check
    @function
    async def pipeline_tools(self) -> None:
        """Check pipeline source and the PR scan selection tests."""
        ctr = (await _python(self.source, "agents")).with_directory(
            "/src", _source(self.source, [".dagger/src/**", "dagger/*/src/**"])
        )
        ctr = ctr.with_exec(["apt-get", "update"]).with_exec(
            ["apt-get", "install", "-y", "--no-install-recommends", "git"]
        )
        paths = [
            ".dagger/src",
            "dagger/socket-firewall/src",
            "dagger/datadog-static-analyzer/src",
            "dagger/actionlint/src",
            "dagger/opengrep/src",
            "scripts",
        ]
        ctr = _run_python(ctr, "agents", ["ruff", "check", *paths])
        ctr = _run_python(ctr, "agents", ["ruff", "format", "--check", *paths])
        await _run_python(ctr, "agents", ["pytest", "scripts"]).stdout()

    @check
    @function(cache="never")
    async def socket_cli(self) -> None:
        """Also exercise the CLI's package and isolated build dependencies."""
        await (await _python(self.source, "safari-history-export", fresh=True)).stdout()

    @check
    @function(cache="never")
    async def socket_frontend(self) -> None:
        """Recheck Node downloads without a package-store cache mount."""
        await (await _frontend(self.source, fresh=True)).stdout()

    @function
    async def datadog_report(self, source: Directory | None = None) -> Directory:
        """Export SARIF and exit-code together, including when findings fail policy."""
        if source is None:
            source = _source(
                self.source,
                [
                    "backend/**",
                    "cli/**",
                    "frontend/**",
                    "scripts/**",
                    "infrastructure/*.tf",
                    ".github/**",
                    "*.yaml",
                    "*.toml",
                    ".gitignore",
                    "**/.gitignore",
                    ".dagger/src/**",
                    "dagger/*/src/**",
                ],
            )
        result = datadog_static_analyzer().scan(source)
        # Force report validation before returning an exportable directory.
        import json

        report = result.sarif()
        parsed = json.loads(await report.contents())
        if parsed.get("version") != "2.1.0" or not isinstance(parsed.get("runs"), list):
            raise ValueError("Datadog did not produce valid SARIF")
        # Match our OpenGrep integration: GitHub can surface in-source suppressed
        # SARIF findings as alerts. Keep the analyzer's original status and logs.
        for run in parsed["runs"]:
            run["results"] = [
                result
                for result in run.get("results", [])
                if not result.get("suppressions")
            ]
        return (
            core()
            .directory()
            .with_new_file("results.sarif", json.dumps(parsed))
            .with_new_file("exit-code", str(await result.exit_code()))
            .with_new_file("scan.log", await result.logs())
        )

    @function(cache="session")
    async def opengrep_report(self, source: Directory | None = None) -> Directory:
        """Export portable OpenGrep findings before enforcing scan policy."""
        import json

        result = opengrep().scan(source if source is not None else self.source)
        parsed = json.loads(await result.sarif().contents())
        if parsed.get("version") != "2.1.0" or not isinstance(parsed.get("runs"), list):
            raise ValueError("OpenGrep did not produce valid SARIF")
        # GitHub's SARIF ingestion surfaces suppressed results as alerts.
        for run in parsed["runs"]:
            run["results"] = [
                result
                for result in run.get("results", [])
                if not result.get("suppressions")
            ]
        return (
            core()
            .directory()
            .with_new_file("results.sarif", json.dumps(parsed))
            .with_new_file("exit-code", str(await result.policy_exit_code()))
            .with_new_file("raw-exit-code", str(await result.exit_code()))
            .with_new_file("scan.log", await result.logs())
        )

    @function
    def image(self, platform: str = "linux/amd64") -> Container:
        """Build the authoritative production Dockerfile with protected installs."""
        if platform not in ("linux/amd64", "linux/arm64"):
            raise ValueError(f"unsupported release platform: {platform}")
        return _source(
            self.source,
            [
                "backend/**",
                "frontend/**",
                "pyproject.toml",
                "uv.lock",
                "cli/pyproject.toml",
                ".dockerignore",
                "dagger/socket-firewall/src/socket_firewall/checksums.sha256",
            ],
        ).docker_build(dockerfile="backend/Dockerfile", platform=Platform(platform))

    @check
    @function
    async def image_amd64(self) -> None:
        await self.image("linux/amd64").sync()

    @check
    @function
    async def image_arm64(self) -> None:
        await self.image("linux/arm64").sync()

    @check
    @function
    async def smoke(self) -> None:
        """Run migrations and all frontend/API/CLI seams against the release image."""
        # A distinct service definition keeps destructive pytest fixtures isolated.
        db = self.postgres(database="smoke")
        image = self.image(
            "linux/arm64"
            if str(await core().default_platform()).startswith("linux/arm64")
            else "linux/amd64"
        )
        configured = (
            image.with_service_binding("postgres", db)
            .with_env_variable(
                "DATABASE_URL", "postgresql://agents:agents@postgres:5432/smoke"
            )
            .with_env_variable("GOOGLE_CLIENT_ID", "smoke-test")
            .with_env_variable("GOOGLE_CLIENT_SECRET", "smoke-test")
            .with_env_variable("ALLOWED_EMAILS", "smoke@example.com")
        )
        await configured.with_exec(
            [
                "/app/.venv/bin/alembic",
                "-c",
                "/app/alembic.ini",
                "upgrade",
                "head",
            ]
        ).sync()
        app = configured.with_exposed_port(8080).as_service(use_entrypoint=True)
        client = (
            (await _python(self.source, "safari-history-export"))
            .with_directory("/src", _source(self.source, ["scripts/**"]))
            .with_env_variable("UV_NO_SYNC", "1")
            .with_env_variable("SMOKE_REQUIRE_ALL", "1")
            .with_service_binding("app", app)
        )
        await client.with_exec(
            ["python", "scripts/smoke_test.py", "http://app:8080"]
        ).stdout()

    @function(cache="never")
    async def publish(
        self, address: str, registry: str, password: Secret, username: str = "AWS"
    ) -> str:
        """Publish both release architectures and return the manifest digest address."""
        return (
            await core()
            .container()
            .with_registry_auth(registry, username, password)
            .publish(
                address,
                platform_variants=[
                    self.image("linux/amd64"),
                    self.image("linux/arm64"),
                ],
            )
        )
