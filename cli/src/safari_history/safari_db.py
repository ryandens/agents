"""Reading Safari's history database.

Private Browsing never appears here. Safari keeps those windows out of the history
database entirely rather than flagging them, so there is no filter to apply and no way
for this exporter to leak them — worth stating explicitly, because it is the kind of
property that is otherwise only true by accident.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from safari_history.errors import (
    DatabaseMissing,
    DatabaseUnreadable,
    FullDiskAccessRequired,
)

DEFAULT_DATABASE = Path.home() / "Library" / "Safari" / "History.db"

# Safari stores visit_time as a CFAbsoluteTime: seconds since 2001-01-01 00:00:00 UTC.
# Derived rather than written as 978307200 so the number cannot drift from its meaning —
# the 31-year off-by-one is the classic bug in scripts that do this with sqlite3 and date.
SAFARI_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
SAFARI_EPOCH_OFFSET = SAFARI_EPOCH.timestamp()

# history_visits holds the timestamp and the title as it was at that moment;
# history_items holds the url. Joining them is what turns "a visit" into a row someone
# can read later. Redirect hops are included: they are real navigations, and dropping
# them would quietly rewrite the story of how a page was reached.
_VISITS_QUERY = """
    SELECT v.visit_time, COALESCE(v.title, ''), COALESCE(i.url, '')
    FROM history_visits v
    JOIN history_items i ON i.id = v.history_item
    WHERE v.visit_time >= ? AND v.visit_time < ?
    ORDER BY v.visit_time ASC
"""


@dataclass(frozen=True)
class Visit:
    visited_at: datetime
    title: str
    url: str


def to_safari_time(moment: datetime) -> float:
    return moment.timestamp() - SAFARI_EPOCH_OFFSET


def from_safari_time(visit_time: float) -> datetime:
    """A Safari timestamp as an aware datetime in the machine's local zone.

    Truncated to whole seconds. Safari's sub-second precision is noise for a daily
    export, and it makes the API's (timestamp, url) deduplication behave predictably
    when the same day is exported twice.
    """
    moment = datetime.fromtimestamp(visit_time + SAFARI_EPOCH_OFFSET, tz=UTC)
    return moment.replace(microsecond=0).astimezone()


def day_bounds(day: date) -> tuple[float, float]:
    """The half-open span `[start, end)` of one local day, as Safari timestamps.

    Anchored to local midnight on both ends and converted with each end's own UTC
    offset, so the two days a year that are 23 or 25 hours long still export exactly
    one day of visits.
    """
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return to_safari_time(start), to_safari_time(end)


def _check_reachable(database: Path) -> None:
    """Fail early, and specifically, on the two failures that are not really SQLite's.

    A TCC denial reaches sqlite3 as the far less actionable "unable to open database
    file". Opening the file directly first is what makes the difference between a log
    line that names Full Disk Access and one that does not.
    """
    if not database.exists():
        raise DatabaseMissing.for_path(database)
    try:
        with open(database, "rb") as handle:
            handle.read(16)
    except PermissionError as exc:
        raise FullDiskAccessRequired.for_path(database) from exc
    except OSError as exc:
        raise DatabaseUnreadable.damaged(database, str(exc)) from exc


@contextmanager
def _snapshot(database: Path) -> Iterator[Path]:
    """Copy the database aside and hand back the copy.

    Safari runs History.db in WAL mode and holds it open all day. Reading it in place
    means either contending with those locks or opening it immutable and quietly missing
    everything still in the write-ahead log. A private copy is consistent, cannot
    disturb Safari, and makes it impossible for a bug here to modify real history.
    """
    with tempfile.TemporaryDirectory(prefix="safari-history-export-") as workspace:
        snapshot = Path(workspace) / "History.db"
        try:
            shutil.copy2(database, snapshot)
            # The -wal holds visits Safari has committed but not yet checkpointed —
            # usually everything from the last few minutes. Skipping it is how an
            # exporter ends up missing the most recent browsing. Both sidecars are
            # absent when Safari has checkpointed cleanly, which is normal.
            for suffix in ("-wal", "-shm"):
                sidecar = database.with_name(database.name + suffix)
                if sidecar.exists():
                    shutil.copy2(sidecar, snapshot.with_name(snapshot.name + suffix))
        except PermissionError as exc:
            raise FullDiskAccessRequired.for_path(database) from exc
        except OSError as exc:
            raise DatabaseUnreadable.snapshot_failed(database, str(exc)) from exc
        yield snapshot


def read_visits(day: date, database: Path = DEFAULT_DATABASE) -> list[Visit]:
    """Every visit Safari recorded on `day`, in local time, oldest first."""
    _check_reachable(database)
    start, end = day_bounds(day)

    with _snapshot(database) as snapshot:
        # Opened read-write even though nothing here writes: recovering the -wal into
        # the snapshot is itself a write, and a read-only open of a WAL database fails
        # when SQLite cannot create its -shm. This is a throwaway copy, so letting
        # SQLite fix it up costs nothing and Safari's real file is untouched either way.
        try:
            connection = sqlite3.connect(snapshot)
        except sqlite3.Error as exc:
            raise DatabaseUnreadable.damaged(snapshot, str(exc)) from exc

        try:
            rows = connection.execute(_VISITS_QUERY, (start, end)).fetchall()
        except sqlite3.OperationalError as exc:
            detail = str(exc)
            if "locked" in detail or "busy" in detail:
                raise DatabaseUnreadable.locked(snapshot, detail) from exc
            # "no such table"/"no such column" means the schema moved under us, which is
            # a different problem from a corrupt file and needs a different fix.
            if "no such" in detail:
                raise DatabaseUnreadable.schema_changed(detail) from exc
            raise DatabaseUnreadable.damaged(snapshot, detail) from exc
        except sqlite3.DatabaseError as exc:
            raise DatabaseUnreadable.damaged(snapshot, str(exc)) from exc
        finally:
            connection.close()

    return [
        Visit(visited_at=from_safari_time(visit_time), title=title, url=url)
        # A visit with no url is not something anyone can act on later, and it would
        # land in the CSV as a blank column.
        for visit_time, title, url in rows
        if url
    ]
