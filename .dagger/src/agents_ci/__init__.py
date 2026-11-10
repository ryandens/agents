import re
import uuid
from typing import Self

from dagger_clients.core import (
    Container,
    Directory,
    Service,
    Workspace,
    core,
)
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
    """Portable application checks over explicit source inputs."""

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
    async def module_contracts(self) -> None:
        """Blocked installs must fail while preserving caller arguments and environment."""
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
        """Lint the handwritten pipeline and reusable Socket module."""
        ctr = (await _python(self.source, "agents")).with_directory(
            "/src",
            _source(
                self.source,
                [
                    ".dagger/src/**",
                    "dagger/socket-firewall/src/**",
                    "scripts/dagger_workspace.py",
                ],
            ),
        )
        paths = [
            ".dagger/src",
            "dagger/socket-firewall/src",
            "scripts/dagger_workspace.py",
        ]
        ctr = _run_python(ctr, "agents", ["ruff", "check", *paths])
        await _run_python(ctr, "agents", ["ruff", "format", "--check", *paths]).stdout()

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
