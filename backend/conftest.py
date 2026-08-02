"""Shared fixtures: a real Postgres for anything that touches the pantry store.

The store is almost entirely SQL, so a fake would test the fake. These tests run against
a Postgres container started once per session — the same engine Aurora runs in
production, and close enough in version that behaviour differences are not a concern.

Docker is therefore a prerequisite for `just backend-test`. Set TEST_DATABASE_URL to
point at a server you already have instead; note that the fixtures TRUNCATE between
tests, so do not point it at a database holding anything you want to keep.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from alembic import command
from alembic.config import Config
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

import db
from browser_history_store import BrowserHistoryStore
from pantry_store import PantryStore

BACKEND_DIR = Path(__file__).parent

# Matched to the Aurora PostgreSQL major version in infrastructure/rds.tf and to the
# container `just db-up` runs locally, so all three agree.
POSTGRES_IMAGE = "postgres:17-alpine"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return

    # driver=None asks for a bare `postgresql://` URL rather than the SQLAlchemy-style
    # `postgresql+psycopg2://` default, which psycopg cannot parse.
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as postgres:
        yield postgres.get_connection_url()


def run_migrations(database_url: str) -> None:
    """Bring a database up to head with the real Alembic migrations.

    The tests run the same migrations production does rather than a copy of the schema
    kept alongside them. A duplicate would drift, and the first sign of it would be a
    test suite that passes against a schema the deploy never creates.
    """
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # env.py reads DATABASE_URL; setting it here keeps the whole configuration in one
    # place instead of splitting it between the env and the Config object.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    run_migrations(database_url)
    return database_url


@pytest.fixture(scope="session")
def pool(migrated_database: str) -> Iterator[ConnectionPool]:
    pool = db.open_pool(migrated_database)
    yield pool
    pool.close()


@pytest.fixture
def clean_database(pool: ConnectionPool) -> ConnectionPool:
    """Empty every table before each test, so tests do not see each other's rows."""
    with pool.connection() as conn:
        conn.execute("TRUNCATE pantry_items, browser_visits")
    return pool


@pytest.fixture
def store(clean_database: ConnectionPool) -> PantryStore:
    return PantryStore(clean_database)


@pytest.fixture
def history_store(clean_database: ConnectionPool) -> BrowserHistoryStore:
    return BrowserHistoryStore(clean_database)


@pytest.fixture
def unmigrated_database(database_url: str) -> Iterator[str]:
    """A scratch database with no migrations applied.

    Exists so a test can assert the *absence* of schema creation. The session database
    is migrated once and shared, so it cannot answer "would the app have created this
    table itself?" — only a database nothing has migrated can.
    """
    import psycopg

    name = "unmigrated_probe"
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {name}")

    # Swap only the path, so the result is still a URL. A libpq keyword string
    # ("host=… dbname=…") would work for psycopg but not for SQLAlchemy, which Alembic
    # parses the DSN with — and this fixture is handed to both.
    parts = urlparse(database_url)
    yield urlunparse(parts._replace(path=f"/{name}"))

    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
