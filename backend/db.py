"""Postgres connection pool and schema bootstrap.

The pantry lives in Postgres — Aurora Serverless v2 in production, a container locally
and in tests. Nothing about the app is Aurora-specific; it is a plain Postgres client.
"""

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Matches what `just db-up` starts. Only a default: production passes DATABASE_URL, built
# by the systemd unit from the Aurora endpoint and the password it reads from Parameter
# Store. Deliberately not a secret — the local container is reachable on loopback only.
DEFAULT_DATABASE_URL = "postgresql://agents:agents@127.0.0.1:5432/agents"

# One statement per element, because psycopg only sends multiple statements in a single
# execute() under the simple query protocol — a detail not worth depending on.
#
# The enums (category, unit, storage_location) are stored as TEXT and validated by
# pydantic on the way out rather than by a CHECK constraint. Unit alone has twenty
# members and both it and Category are expected to grow; a constraint would turn every
# new member into a schema migration for no protection the API layer does not already
# give, since nothing writes to this table except the app.
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS pantry_items (
        id                UUID PRIMARY KEY,
        name              TEXT NOT NULL,
        brand             TEXT,
        category          TEXT NOT NULL,
        storage_location  TEXT NOT NULL,
        quantity          DOUBLE PRECISION NOT NULL,
        unit              TEXT NOT NULL,
        purchase_date     DATE,
        expiration_date   DATE,
        notes             TEXT,
        created_at        TIMESTAMPTZ NOT NULL,
        updated_at        TIMESTAMPTZ NOT NULL
    )
    """,
    # The one query shape the API filters on.
    """
    CREATE INDEX IF NOT EXISTS pantry_items_storage_location_idx
        ON pantry_items (storage_location)
    """,
]


def database_url() -> str:
    """Where to connect. Empty and unset both mean "use the local default"."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def open_pool(url: str | None = None, *, timeout: float = 60.0) -> ConnectionPool:
    """Open a pool and wait for the first connection to succeed.

    Waiting matters in production: an idle Aurora Serverless v2 cluster scales to zero
    and takes some seconds to resume, and the boot health check is what decides whether
    the deploy was good. Failing fast on a paused database would fail every deploy that
    happened to follow a quiet night, so the timeout is generous rather than tight.
    """
    pool = ConnectionPool(
        url if url is not None else database_url(),
        # Rows come back as dicts so pydantic can validate them straight into models.
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=8,
        # Hands out a connection only after checking it is still alive. Long-lived
        # pooled connections otherwise survive an Aurora failover or scale-down event
        # as sockets that error on first use.
        check=ConnectionPool.check_connection,
        open=False,
    )
    pool.open(wait=True, timeout=timeout)
    return pool


def apply_schema(pool: ConnectionPool) -> None:
    """Create the schema if it is not there yet.

    One table with no history behind it, so `CREATE TABLE IF NOT EXISTS` at startup is
    the whole migration story. A second table — or a column that has to change shape on
    a table holding real rows — is the point at which this should become Alembic.
    """
    with pool.connection() as conn:
        for statement in SCHEMA:
            conn.execute(statement)


def ping(pool: ConnectionPool, *, timeout: float = 5.0) -> None:
    """Raise if the database is not answering. Used by /health."""
    with pool.connection(timeout=timeout) as conn:
        conn.execute("SELECT 1")
