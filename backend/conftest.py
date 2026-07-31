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

import pytest
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

import db
from pantry_store import PantryStore

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


@pytest.fixture(scope="session")
def pool(database_url: str) -> Iterator[ConnectionPool]:
    pool = db.open_pool(database_url)
    db.apply_schema(pool)
    yield pool
    pool.close()


@pytest.fixture
def clean_database(pool: ConnectionPool) -> ConnectionPool:
    """Empty the pantry before each test, so tests do not see each other's rows."""
    with pool.connection() as conn:
        conn.execute("TRUNCATE pantry_items")
    return pool


@pytest.fixture
def store(clean_database: ConnectionPool) -> PantryStore:
    return PantryStore(clean_database)
