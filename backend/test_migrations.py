"""Tests for the migration runner itself, not for any particular migration.

These exist because of a bug that shipped nothing while reporting success. env.py takes
an advisory lock before handing control to Alembic; on a SQLAlchemy 2.0 connection that
first `execute()` opens an implicit transaction, so Alembic's per-migration commits
became nested no-ops inside it and `with engine.connect()` rolled the whole run back on
exit. The log said "Running upgrade -> 0001" and the database was left empty.

The lesson those tests encode: **assert on a connection the migration did not use.**
Checking through the migrating connection would have seen the uncommitted work and
passed.
"""

import os
import shutil

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.rows import dict_row

from conftest import BACKEND_DIR, run_migrations


def inspect(url: str, sql: str, params: tuple = ()):
    """Query over a brand-new connection, outside any migration transaction."""
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchone()


def alembic_config(script_location: str | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option(
        "script_location", script_location or str(BACKEND_DIR / "migrations")
    )
    return config


def head_revision() -> str:
    """The newest revision on disk.

    Read from the script directory rather than written down here, so adding a migration
    does not require editing the tests that assert the database reached head — a chore
    that invites pinning the assertion to whatever the code currently does.
    """
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None, "no migrations found"
    return head


def test_migrations_are_committed(unmigrated_database: str) -> None:
    """The regression test: a separate connection must see the migrated schema."""
    run_migrations(unmigrated_database)

    for table in ("pantry_items", "browser_visits", "alembic_version"):
        row = inspect(unmigrated_database, "SELECT to_regclass(%s) AS t", (table,))
        assert row is not None and row["t"] == table, (
            f"{table} is missing after a migration that reported success — "
            "the run was rolled back"
        )


def test_migrations_record_the_head_revision(unmigrated_database: str) -> None:
    run_migrations(unmigrated_database)

    row = inspect(unmigrated_database, "SELECT version_num FROM alembic_version")
    assert row is not None and row["version_num"] == head_revision()


def test_migrations_are_idempotent(unmigrated_database: str) -> None:
    """A second run is what every redeploy does, so it must be a no-op, not an error."""
    run_migrations(unmigrated_database)
    run_migrations(unmigrated_database)

    row = inspect(unmigrated_database, "SELECT count(*) AS n FROM alembic_version")
    assert row is not None and row["n"] == 1


def test_migration_releases_the_advisory_lock(unmigrated_database: str) -> None:
    """A lock left held would block the next deploy rather than the next migration."""
    run_migrations(unmigrated_database)

    row = inspect(
        unmigrated_database,
        "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory'",
    )
    assert row is not None and row["n"] == 0


def test_schema_matches_what_the_store_writes(unmigrated_database: str) -> None:
    """The migration and pantry_store must agree on the column list.

    pantry_store names every column explicitly in its INSERT. If a migration adds a
    NOT NULL column without a default, or renames one, the store keeps working in tests
    that only exercise the old columns and fails in production on the first write.
    """
    from pantry_store import _COLUMNS

    run_migrations(unmigrated_database)

    with psycopg.connect(unmigrated_database, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'pantry_items'"
        ).fetchall()

    assert {r["column_name"] for r in rows} == set(_COLUMNS)


@pytest.mark.parametrize(
    "column", ["name", "category", "storage_location", "quantity", "unit"]
)
def test_not_null_columns_match_the_store_backstop(
    unmigrated_database: str, column: str
) -> None:
    """pantry_store refuses to null these; the table must actually declare them NOT NULL.

    If the two drift, the backstop is either useless or rejecting something the schema
    would have accepted.
    """
    run_migrations(unmigrated_database)

    row = inspect(
        unmigrated_database,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'pantry_items' AND column_name = %s",
        (column,),
    )
    assert row is not None and row["is_nullable"] == "NO"


def test_a_failing_revision_keeps_the_ones_before_it(
    unmigrated_database: str, tmp_path
) -> None:
    """Each revision commits on its own, so a later failure does not undo earlier ones.

    transaction_per_migration is what makes a partially-applied batch land on a real
    revision rather than rolling everything back — the database ends up at the last
    revision that succeeded, which is a state the next deploy can resume from. Pinned
    here because it is a property of how env.py drives Alembic, not something Alembic
    guarantees on its own.
    """
    versions = tmp_path / "versions"
    versions.mkdir(parents=True)
    shutil.copy(BACKEND_DIR / "migrations" / "env.py", tmp_path / "env.py")
    shutil.copy(
        BACKEND_DIR / "migrations" / "script.py.mako", tmp_path / "script.py.mako"
    )
    for migration in (BACKEND_DIR / "migrations" / "versions").glob("*.py"):
        shutil.copy(migration, versions / migration.name)

    # Chained onto the real head rather than onto a fixed revision, so this stays a
    # linear history as migrations are added. A hardcoded down_revision would branch
    # the tree the moment it stopped naming the newest one, and Alembic would fail
    # with "multiple head revisions" instead of the failure this test is about.
    last_good = head_revision()
    (versions / "9999_boom.py").write_text(
        'revision = "9999"\n'
        f'down_revision = "{last_good}"\n'
        "branch_labels = None\n"
        "depends_on = None\n"
        "\n"
        "def upgrade():\n"
        '    raise RuntimeError("deliberate failure")\n'
        "\n"
        "def downgrade():\n"
        "    pass\n"
    )

    config = alembic_config(str(tmp_path))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = unmigrated_database
    try:
        with pytest.raises(RuntimeError, match="deliberate failure"):
            command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous

    # The real migrations survived the failure of 9999, and the recorded revision
    # says so.
    row = inspect(unmigrated_database, "SELECT to_regclass('pantry_items') AS t")
    assert row is not None and row["t"] == "pantry_items"
    row = inspect(unmigrated_database, "SELECT version_num FROM alembic_version")
    assert row is not None and row["version_num"] == last_good
