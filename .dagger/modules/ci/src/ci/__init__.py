import dagger
from dagger import check, dag, function, object_type


@object_type
class Ci:
    source: dagger.Directory

    def __init__(self, *, source: dagger.Directory) -> None:
        # Explicitly mirrors the initializer @object_type would generate. Keeping it
        # visible also lets static analyzers understand how the required field is set.
        self.source = source

    @classmethod
    def create(cls, ws: dagger.Workspace) -> "Ci":
        return cls(
            source=ws.directory(
                "/",
                exclude=[
                    ".git",
                    ".claude",
                    ".venv",
                    "**/__pycache__",
                    "**/node_modules",
                    "backend/static",
                    "frontend/.next",
                    "frontend/out",
                ],
            )
        )

    def python(self) -> dagger.Container:
        return (
            dag.container()
            .from_("cgr.dev/chainguard/python:latest-dev@sha256:e8e6a6f7677673d91c9b28fa2ec6ad62cd5ed532179846d2c14e75c93a12c3fc")
            .with_user("root")
            .with_file(
                "/usr/local/bin/uv",
                dag.container().from_("ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168").file("/uv"),
            )
            .with_directory("/src", self.source)
            .with_workdir("/src")
            .with_mounted_cache("/root/.cache/uv", dag.cache_volume("uv"))
        )

    def postgres(self) -> dagger.Service:
        return (
            dag.container()
            .from_("postgres:17-alpine")
            .with_env_variable("POSTGRES_USER", "agents")
            .with_env_variable("POSTGRES_PASSWORD", "agents")
            .with_env_variable("POSTGRES_DB", "agents")
            .with_exposed_port(5432)
            .as_service()
        )

    @function
    @check
    async def backend(self) -> None:
        """Lint, format-check, and test the backend against ephemeral PostgreSQL."""
        await (
            self.python()
            .with_service_binding("database", self.postgres())
            .with_env_variable(
                "TEST_DATABASE_URL",
                "postgresql://agents:agents@database:5432/agents",
            )
            .with_exec(["uv", "sync", "--locked", "--package", "agents"])
            .with_exec(["uv", "run", "--locked", "--package", "agents", "ruff", "check", "backend", "scripts"])
            .with_exec(["uv", "run", "--locked", "--package", "agents", "ruff", "format", "--check", "backend", "scripts"])
            .with_exec(["uv", "run", "--locked", "--package", "agents", "pytest", "backend"])
            .sync()
        )

    @function
    @check
    async def cli(self) -> None:
        """Lint, format-check, and test the Safari history exporter."""
        await (
            self.python()
            .with_exec(["uv", "sync", "--locked", "--package", "safari-history-export"])
            .with_exec(["uv", "run", "--locked", "--package", "safari-history-export", "ruff", "check", "cli"])
            .with_exec(["uv", "run", "--locked", "--package", "safari-history-export", "ruff", "format", "--check", "cli"])
            .with_exec(["uv", "run", "--locked", "--package", "safari-history-export", "pytest", "cli"])
            .sync()
        )

    @function
    @check
    async def frontend(self) -> None:
        """Install, lint, build, and test the frontend."""
        await (
            dag.container()
            .from_("node:24.21.0-slim")
            .with_directory("/src", self.source)
            .with_workdir("/src/frontend")
            .with_mounted_cache("/pnpm/store", dag.cache_volume("pnpm"))
            .with_env_variable("PNPM_HOME", "/pnpm")
            .with_env_variable("PATH", "/pnpm:$PATH", expand=True)
            .with_exec(["corepack", "enable"])
            .with_exec(["pnpm", "install", "--frozen-lockfile"])
            .with_exec(["pnpm", "run", "lint"])
            .with_exec(["pnpm", "run", "build"])
            .with_exec(["pnpm", "run", "test"])
            .sync()
        )

    @function
    @check
    async def image(self) -> None:
        """Build and smoke-test the production image with ephemeral PostgreSQL."""
        image = self.source.docker_build(dockerfile="backend/Dockerfile")
        database = self.postgres()
        database_url = "postgresql://agents:agents@database:5432/agents"

        await (
            image.with_service_binding("database", database)
            .with_env_variable("DATABASE_URL", database_url)
            .with_exec(
                [
                    "/app/.venv/bin/alembic",
                    "-c",
                    "/app/alembic.ini",
                    "upgrade",
                    "head",
                ]
            )
            .sync()
        )

        app = (
            image.with_service_binding("database", database)
            .with_env_variable("DATABASE_URL", database_url)
            .with_env_variable("GOOGLE_CLIENT_ID", "smoke-test")
            .with_env_variable("GOOGLE_CLIENT_SECRET", "smoke-test")
            .with_env_variable("ALLOWED_EMAILS", "smoke@example.com")
            .with_exposed_port(8080)
            .as_service(use_entrypoint=True)
        )
        await (
            self.python()
            .with_service_binding("app", app)
            .with_exec(["python3", "scripts/smoke_test.py", "http://app:8080"])
            .sync()
        )
