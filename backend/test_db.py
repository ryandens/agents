"""Tests for the connection layer, and especially the IAM auth path.

Production authenticates with a token instead of a password, and that path cannot be
exercised against real RDS from here. What it *can* be checked against is a plain
Postgres: the mechanism is "call a function at connect time and use whatever it returns
as the password", so pointing the token function at the container's own password proves
the wiring — the token is minted, it reaches libpq, and it overrides the DSN.
"""

from urllib.parse import parse_qsl, urlparse

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

import db

# --- Configuration ---


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " true "])
def test_iam_auth_enabled_accepts_truthy_values(monkeypatch, value: str) -> None:
    monkeypatch.setenv("DATABASE_IAM_AUTH", value)
    assert db.iam_auth_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_iam_auth_disabled_by_default_and_for_falsy_values(
    monkeypatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_IAM_AUTH", value)
    assert db.iam_auth_enabled() is False


def test_iam_auth_disabled_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_IAM_AUTH", raising=False)
    assert db.iam_auth_enabled() is False


# --- Token-based connections ---


def test_iam_connection_authenticates_with_the_minted_token(
    database_url: str, monkeypatch
) -> None:
    """The token is what gets used, and it is built from the DSN's own host/port/user."""
    params = conninfo_to_dict(database_url)
    calls = []

    def fake_token(host: str, port: int, user: str) -> str:
        calls.append((host, port, user))
        return str(params["password"])

    monkeypatch.setattr(db, "generate_auth_token", fake_token)

    with db.IamConnection.connect(database_url) as conn:
        assert conn.execute("SELECT 1 AS ok").fetchone()[0] == 1

    assert calls == [(params["host"], int(params["port"]), params["user"])]


def test_iam_connection_ignores_any_password_in_the_dsn(
    database_url: str, monkeypatch
) -> None:
    """A wrong token fails even though the DSN carries a working password.

    This is the test that makes the one above mean something: without it, a connection
    succeeding proves only that the DSN worked, not that the token was consulted.
    """
    monkeypatch.setattr(db, "generate_auth_token", lambda host, port, user: "not-it")

    with pytest.raises(psycopg.OperationalError):
        db.IamConnection.connect(database_url)


def test_iam_connection_mints_a_fresh_token_per_connection(
    database_url: str, monkeypatch
) -> None:
    """Tokens expire after 15 minutes, so reusing one across connections would rot."""
    params = conninfo_to_dict(database_url)
    minted = []

    def fake_token(host: str, port: int, user: str) -> str:
        minted.append(object())
        return str(params["password"])

    monkeypatch.setattr(db, "generate_auth_token", fake_token)

    for _ in range(3):
        with db.IamConnection.connect(database_url):
            pass

    assert len(minted) == 3


def test_iam_connection_rejects_a_dsn_without_host_or_user(monkeypatch) -> None:
    """Fail with something readable rather than signing a token for None."""
    monkeypatch.setattr(
        db, "generate_auth_token", lambda host, port, user: "unused-token"
    )

    with pytest.raises(ValueError, match="DATABASE_IAM_AUTH"):
        db.IamConnection.connect("dbname=agents")


def test_pool_uses_iam_connections_when_asked(database_url: str, monkeypatch) -> None:
    """open_pool wires the connection class through, so the pool mints tokens too."""
    params = conninfo_to_dict(database_url)
    calls = []

    def fake_token(host: str, port: int, user: str) -> str:
        calls.append(user)
        return str(params["password"])

    monkeypatch.setattr(db, "generate_auth_token", fake_token)

    pool = db.open_pool(database_url, timeout=15.0, iam_auth=True)
    try:
        assert pool.connection_class is db.IamConnection
        with pool.connection() as conn:
            # dict_row, because open_pool configures it — unlike the direct connects above.
            assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    finally:
        pool.close()

    assert calls, "the pool opened a connection without minting a token"


def test_pool_uses_password_auth_by_default(database_url: str, monkeypatch) -> None:
    """The local and test paths must not reach for AWS."""
    monkeypatch.delenv("DATABASE_IAM_AUTH", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("password auth must not mint an IAM token")

    monkeypatch.setattr(db, "generate_auth_token", explode)

    pool = db.open_pool(database_url, timeout=15.0)
    try:
        assert pool.connection_class is psycopg.Connection
        with pool.connection() as conn:
            assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    finally:
        pool.close()


# --- Token generation ---


def test_generate_auth_token_signs_a_connect_request(monkeypatch) -> None:
    """The real boto3 call, checked without AWS: SigV4 signing is local and offline.

    This is the one piece the fakes above deliberately skip, and it is where a wrong
    argument name or a wrong service scope would hide — the resulting token would look
    fine and be rejected only by RDS, in production.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv(
        "AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    )
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    host = "agents.cluster-abc123.us-east-1.rds.amazonaws.com"
    token = db.generate_auth_token(host, 5432, "agents_app")

    assert token.startswith(f"{host}:5432/")
    query = dict(parse_qsl(urlparse(f"//{token}").query))
    assert query["Action"] == "connect"
    assert query["DBUser"] == "agents_app"
    # Scoped to the rds-db service, not rds: a token signed for the wrong one is
    # accepted by nothing and explains nothing when it fails.
    assert "/rds-db/aws4_request" in query["X-Amz-Credential"]
    assert query["X-Amz-Expires"] == "900"
    assert query["X-Amz-Signature"]
