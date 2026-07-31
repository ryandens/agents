#!/usr/bin/env python3
"""Load a pantry.json — the old file-backed store — into Postgres.

One-time migration, kept because the file was the only copy of the pantry before this
and a deployed instance's copy does not survive being replaced. Grab it off the box
first if it is still there:

    just ssh
    sudo cat /opt/agents/data/pantry.json

then, from a machine that can reach the database:

    just db-import                                  # backend/data/pantry.json → local
    just db-import pantry.json "$DATABASE_URL"      # some other file, some other database

Re-running is safe: rows are matched on the id already in the file, and an id that is
already present is left alone rather than overwritten, so this cannot clobber edits made
since an earlier import.

Unlike scripts/smoke_test.py this is not stdlib-only — it needs psycopg, so run it
through `uv run --project backend` (which is what `just db-import` does).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

COLUMNS = (
    "id",
    "name",
    "brand",
    "category",
    "storage_location",
    "quantity",
    "unit",
    "purchase_date",
    "expiration_date",
    "notes",
    "created_at",
    "updated_at",
)

INSERT = f"""
INSERT INTO pantry_items ({", ".join(COLUMNS)})
VALUES ({", ".join(["%s"] * len(COLUMNS))})
ON CONFLICT (id) DO NOTHING
"""


def rows(items: list[dict]) -> list[tuple]:
    """One tuple per item, in COLUMNS order.

    Values go across as the strings the JSON holds. Postgres casts them itself, because
    psycopg sends a str with an unspecified type and lets the server infer it from the
    target column — so "2026-12-01" lands in a DATE and an ISO timestamp in a TIMESTAMPTZ
    without this having to parse either.
    """
    return [tuple(item.get(column) for column in COLUMNS) for item in items]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(f"usage: {argv[0]} <pantry.json> <database-url>", file=sys.stderr)
        return 2

    path, database_url = Path(argv[1]), argv[2]
    if not path.is_file():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 1

    items = json.loads(path.read_text())
    if not isinstance(items, list):
        print(f"error: {path} is not a JSON list of pantry items", file=sys.stderr)
        return 1
    if not items:
        print(f"{path} holds no items — nothing to import")
        return 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.executemany(INSERT, rows(items))
            imported = cursor.rowcount
        total = conn.execute("SELECT count(*) FROM pantry_items").fetchone()[0]

    skipped = len(items) - imported
    print(
        f"imported {imported} of {len(items)} item(s) from {path}"
        + (f", {skipped} already present" if skipped else "")
        + f" — {total} now in the pantry"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
