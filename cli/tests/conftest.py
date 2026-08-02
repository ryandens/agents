"""A stand-in for Safari's history database.

Not a mock — a *real* SQLite database, the same engine Safari uses, holding synthetic
rows under a trimmed copy of Safari's schema. Only the contents and the unused columns
are invented. Every query, the CFAbsoluteTime conversion, the day-boundary arithmetic
and the WAL snapshot all run for real against it. This mirrors backend/conftest.py,
which starts a real Postgres for the same reason: the code under test is mostly SQL, so
a fake engine would only test the fake.

It exists because the real database cannot be reached from a test. Reading
~/Library/Safari/History.db needs Full Disk Access, its contents differ per machine and
per run, and CI is Linux with no Safari at all. Without this the whole of safari_db.py —
the epoch conversion, the DST-aware day bounds, the snapshot of a live WAL database —
would have no coverage, and those are the parts most worth having it.

The honest limitation: the schema below is a copy, so if Safari ever renames a column
these tests keep passing while the real export breaks. Nothing here can catch that; the
first real run would, because the query would fail loudly rather than return bad rows.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from safari_history.safari_db import to_safari_time
from safari_history.state import local_today

# Trimmed to the columns this exporter reads. Safari's real tables have many more.
SCHEMA = """
CREATE TABLE history_items (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    visit_count INTEGER
);
CREATE TABLE history_visits (
    id INTEGER PRIMARY KEY,
    history_item INTEGER NOT NULL,
    visit_time REAL NOT NULL,
    title TEXT,
    redirect_source INTEGER,
    redirect_destination INTEGER
);
"""


class FakeSafari:
    """Builds a history database with visits at local wall-clock times."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._next_item = 1
        self._next_visit = 1
        with sqlite3.connect(path) as connection:
            connection.executescript(SCHEMA)

    def add_visit(
        self, day: date, at: time, url: str, title: str | None = "A Page"
    ) -> None:
        """Record a visit at a local wall-clock time on `day`."""
        moment = datetime.combine(day, at).astimezone()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO history_items (id, url, visit_count) VALUES (?, ?, 1)",
                (self._next_item, url),
            )
            connection.execute(
                "INSERT INTO history_visits (id, history_item, visit_time, title) "
                "VALUES (?, ?, ?, ?)",
                (self._next_visit, self._next_item, to_safari_time(moment), title),
            )
        self._next_item += 1
        self._next_visit += 1

    def add_orphan_visit(self, day: date, at: time) -> None:
        """A visit whose history_item is gone — the join must drop it."""
        moment = datetime.combine(day, at).astimezone()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO history_visits (id, history_item, visit_time, title) "
                "VALUES (?, 9999, ?, 'Orphan')",
                (self._next_visit, to_safari_time(moment)),
            )
        self._next_visit += 1


@pytest.fixture
def yesterday() -> date:
    return local_today() - timedelta(days=1)


@pytest.fixture
def safari(tmp_path: Path) -> FakeSafari:
    return FakeSafari(tmp_path / "History.db")
