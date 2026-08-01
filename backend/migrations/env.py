"""Alembic environment.

Three things happen here that are not in the generated template, each for a reason:

1. **IAM auth.** Production has no database password. The migrator connects with the
   same short-lived RDS token the app uses, minted per connection — see db.py. SQLAlchemy
   gets it through a `do_connect` hook rather than in the URL, so it is never rendered
   into a string that could be logged.
2. **An advisory lock.** Held for the whole run so two migration processes cannot apply
   the same revision twice. One instance today makes that unlikely, not impossible: a
   deploy racing a boot is enough.
3. **Timeouts.** DDL takes ACCESS EXCLUSIVE, and Postgres grants locks first-come, so
   DDL queued behind one long query blocks every later query on that table. A short
   lock_timeout turns that into a failed migration instead of a stalled application.

There is no `target_metadata` and no autogenerate. The app has no SQLAlchemy models —
it is raw psycopg and pydantic — so migrations are hand-written SQL. `alembic revision
--autogenerate` would produce nothing useful; write the revision by hand.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, event, make_url, pool, text
from sqlalchemy.engine import Engine, create_engine

# The migrations directory sits inside backend/, so importing db needs backend/ on the
# path — Alembic runs with the config directory as cwd, not the package root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A 64-bit key for pg_advisory_lock. Arbitrary but fixed: any process using the same
# number contends with this one, and nothing else in the app takes an advisory lock.
MIGRATION_LOCK_KEY = 8_474_115_302_449_017_001

# Bounded rather than indefinite. If another migration is genuinely running, waiting a
# little is right; waiting forever turns a stuck deploy into a silent hang.
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "60s"
ADVISORY_LOCK_WAIT_SECONDS = 30


def database_url() -> URL:
    """The DSN to migrate, as a SQLAlchemy URL using the psycopg 3 driver.

    DATABASE_URL is a plain libpq URL (`postgresql://...`), which SQLAlchemy would
    otherwise hand to psycopg2. The app has psycopg 3 and nothing else, so the driver is
    named explicitly rather than left to SQLAlchemy's default.
    """
    url = make_url(os.environ.get("DATABASE_URL") or db.DEFAULT_DATABASE_URL)
    return url.set(drivername="postgresql+psycopg")


def build_engine() -> Engine:
    url = database_url()
    engine = create_engine(url, poolclass=pool.NullPool, future=True)

    if db.iam_auth_enabled():
        # Mint a token per connection, exactly as the app does. Registered as an event
        # rather than baked into the URL so the credential has no chance to end up in a
        # log line or an exception's repr.
        @event.listens_for(engine, "do_connect")
        def _inject_iam_token(dialect, conn_rec, cargs, cparams):
            cparams["password"] = db.generate_auth_token(
                str(url.host), int(url.port or 5432), str(url.username)
            )

    return engine


def run_migrations_offline() -> None:
    """Render SQL to stdout instead of applying it (`alembic upgrade head --sql`).

    Useful for review — it shows exactly what a deploy would run — and it takes no lock
    and opens no connection, so it works without AWS credentials.
    """
    context.configure(
        url=database_url().render_as_string(hide_password=True),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine()
    with engine.connect() as connection:
        # Session-scoped, not pg_advisory_xact_lock: the lock has to span several
        # transactions, one per revision, so a transaction-scoped lock would be released
        # after the first one.
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
        ).scalar()
        if not acquired:
            connection.execute(
                text(f"SET lock_timeout = '{ADVISORY_LOCK_WAIT_SECONDS}s'")
            )
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            ).scalar()
        if not acquired:
            raise RuntimeError(
                "another process holds the migration advisory lock "
                f"({MIGRATION_LOCK_KEY}); it is still migrating, or it died holding the "
                "lock and its session has not yet been reaped"
            )

        try:
            # Set after the lock so waiting for the lock is not itself cut short.
            connection.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT}'"))
            connection.execute(text(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'"))

            # End the transaction the statements above implicitly opened — SQLAlchemy 2.0
            # begins one on the first execute() — so that what Alembic commits per
            # revision is the revision and nothing else.
            #
            # The commit that is genuinely load-bearing is the one in the `finally`
            # below. With no commit anywhere, `with engine.connect()` rolls the entire
            # run back on exit and the migration logs "Running upgrade" while applying
            # nothing; test_migrations.py pins that. This one is narrower, and measured
            # rather than assumed: removing it leaves both persistence and per-revision
            # durability intact, so it is scope hygiene, not a correctness fix. It stays
            # because relying on Alembic's transaction handling to nest correctly inside
            # a transaction this file happened to open is a needless thing to depend on.
            #
            # Nothing is lost by committing here: pg_advisory_lock is session-scoped
            # (which is why it is used rather than pg_advisory_xact_lock) and a bare SET
            # is session-scoped too, so both survive.
            connection.commit()

            context.configure(
                connection=connection,
                # One transaction per revision, so a failure half-way through a batch
                # leaves the database at a real revision rather than rolling the whole
                # batch back and losing the ones that worked.
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            connection.commit()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
