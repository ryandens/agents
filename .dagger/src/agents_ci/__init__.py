import re
import uuid
from typing import Self

from dagger_clients.core import (
    Container,
    Directory,
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


def _run_python(ctr: Container, package: str, args: list[str]) -> Container:
    return ctr.with_exec(["uv", "run", "--no-sync", "--package", package, *args])


@object_type
class AgentsCi:
    """Additive CLI checks and reusable Socket tooling."""

    source: Directory = field()

    @classmethod
    async def create(cls, ws: Workspace) -> Self:
        source = (
            ws.directory(
                "/",
                include=[
                    *_MANIFESTS,
                    "backend/Dockerfile",
                    "cli/**",
                    ".dagger/src/**",
                    "dagger/socket-firewall/src/**",
                    "dagger/socket-firewall/tests/**",
                    "scripts/dagger",
                    "scripts/dagger_workspace.py",
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
    async def pipeline_tools(self) -> None:
        """Lint the handwritten pipeline and reusable Socket module."""
        ctr = (await _python(self.source, "safari-history-export")).with_directory(
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
        ctr = _run_python(ctr, "safari-history-export", ["ruff", "check", *paths])
        await _run_python(
            ctr, "safari-history-export", ["ruff", "format", "--check", *paths]
        ).stdout()

    @check
    @function(cache="never")
    async def socket_cli(self) -> None:
        """Also exercise the CLI's package and isolated build dependencies."""
        await (await _python(self.source, "safari-history-export", fresh=True)).stdout()
