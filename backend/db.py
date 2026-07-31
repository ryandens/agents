"""Postgres connection pool and schema bootstrap.

The pantry lives in Postgres — Aurora Serverless v2 in production, a container locally
and in tests. Nothing about the app is Aurora-specific except how it authenticates.

There are two ways in, chosen by DATABASE_IAM_AUTH:

- **Password**, from the DSN. What the local container and the tests use.
- **RDS IAM**, where the password is a token minted per connection from the instance's
  own role. Production uses this, and it means there is no database credential stored
  anywhere — nothing in Parameter Store, nothing in the image, nothing to rotate. The
  token lasts 15 minutes and is signed locally from credentials the instance profile
  hands out, so minting one costs no network round trip.
"""

import logging
import os

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# Matches what `just db-up` starts. Only a default: production passes DATABASE_URL, built
# by the systemd unit from the Aurora endpoint — and carrying no password, because
# production authenticates with IAM. Deliberately not a secret; the local container is
# reachable on loopback only.
DEFAULT_DATABASE_URL = "postgresql://agents:agents@127.0.0.1:5432/agents"


def iam_auth_enabled() -> bool:
    """Whether to authenticate with an RDS IAM token instead of a password."""
    return os.environ.get("DATABASE_IAM_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def generate_auth_token(host: str, port: int, user: str) -> str:
    """Mint a short-lived RDS IAM auth token to use as the password.

    boto3 is imported here rather than at module scope so that the local and test paths,
    which never call this, do not pay for it — and so a missing AWS environment fails
    at connect time with a clear error rather than at import.

    The region comes from the standard AWS_REGION/AWS_DEFAULT_REGION resolution; the
    systemd unit sets it. Credentials come from the instance profile via IMDS, which is
    why the instance's metadata hop limit has to be 2 — the app runs in a container, and
    the bridge network is one hop more than the default allows.
    """
    import boto3

    client = boto3.client("rds")
    return client.generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user, Region=client.meta.region_name
    )


class IamConnection(psycopg.Connection):
    """A connection that authenticates with a freshly minted IAM token.

    The pool calls `connection_class.connect(conninfo, **kwargs)` for every new
    connection, including ones it opens to replace a recycled or broken one, so the
    token is always minted at the moment it is used. That is what makes the 15-minute
    lifetime a non-issue: it never has to outlive the connect that consumes it.
    """

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
        params = conninfo_to_dict(conninfo, **kwargs)
        host, user = params.get("host"), params.get("user")
        if not host or not user:
            raise ValueError(
                "DATABASE_IAM_AUTH needs a host and user in DATABASE_URL; "
                f"got host={host!r} user={user!r}"
            )
        port = int(params.get("port") or 5432)
        # Overrides any password in the DSN, so a stale one left there cannot silently
        # take precedence over the token.
        kwargs["password"] = generate_auth_token(str(host), port, str(user))
        return super().connect(conninfo, **kwargs)


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


def open_pool(
    url: str | None = None, *, timeout: float = 60.0, iam_auth: bool | None = None
) -> ConnectionPool:
    """Open a pool and wait for the first connection to succeed.

    Waiting matters in production: an idle Aurora Serverless v2 cluster scales to zero
    and takes some seconds to resume, and the boot health check is what decides whether
    the deploy was good. Failing fast on a paused database would fail every deploy that
    happened to follow a quiet night, so the timeout is generous rather than tight.
    """
    if iam_auth is None:
        iam_auth = iam_auth_enabled()
    if iam_auth:
        logger.info("authenticating to the database with RDS IAM tokens")

    pool = ConnectionPool(
        url if url is not None else database_url(),
        # Every connection mints its own token; see IamConnection.
        connection_class=IamConnection if iam_auth else psycopg.Connection,
        # Rows come back as dicts so pydantic can validate them straight into models.
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=8,
        # Hands out a connection only after checking it is still alive. Long-lived
        # pooled connections otherwise survive an Aurora failover or scale-down event
        # as sockets that error on first use. Under IAM auth it matters more: a
        # replacement connection is opened here, with a token minted on the spot.
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
