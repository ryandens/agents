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
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from safari_history.errors import (
    DatabaseMissing,
    DatabaseStale,
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


def _check_fresh_enough(database: Path, day: date) -> None:
    """Refuse to infer an empty day from a database Safari has not refreshed.

    Safari can leave History.db untouched while it is closed, including while history
    from other devices is waiting to sync. In that state a successful query returning
    no rows means "not loaded yet", not "no browsing". The WAL counts as an update
    because Safari normally keeps its newest committed visits there until checkpointing.

    Updating at any point during the requested day is sufficient. Requiring an update
    after midnight would strand ordinary days where Safari was closed in the evening.
    """
    sources = (database, database.with_name(database.name + "-wal"))
    try:
        newest = max(path.stat().st_mtime for path in sources if path.exists())
    except OSError as exc:
        raise DatabaseUnreadable.damaged(database, str(exc)) from exc

    start, _ = day_bounds(day)
    start_unix = start + SAFARI_EPOCH_OFFSET
    if newest < start_unix:
        last_updated = datetime.fromtimestamp(newest, tz=UTC).astimezone()
        raise DatabaseStale.for_day(
            database,
            day.isoformat(),
            last_updated.isoformat(timespec="seconds"),
        )


def _backup_into(database: Path, snapshot: Path) -> bool:
    """Snapshot with SQLite's online backup API. True if it worked.

    Preferred over copying the files because it is the only way to get a *consistent*
    view of a database someone else is writing. SQLite takes a read lock for each step
    and restarts the copy if the source changes underneath it, so what lands is always
    a single point in time — WAL contents included, already merged in.

    Opened read-only so this cannot alter Safari's real history even by accident.
    """
    # quote() because a URI filename gives ? and # their URL meanings, and a home
    # directory can contain either.
    uri = f"file:{urllib.parse.quote(str(database))}?mode=ro"
    try:
        source = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        # Most likely a WAL database whose -shm cannot be created, which is what
        # read-only access to a database nobody has open looks like. The file copy
        # below handles that case.
        return False
    # Deliberately not `with sqlite3.connect(...) as destination`: a Connection used as
    # a context manager commits on exit, so closing inside the block makes that commit
    # raise ProgrammingError — which this function would catch and report as "the backup
    # API is unavailable", silently downgrading every export to the inconsistent copy.
    destination = sqlite3.connect(snapshot)
    try:
        source.backup(destination)
        return True
    except sqlite3.Error:
        # Leave nothing half-written for the fallback to trip over.
        snapshot.unlink(missing_ok=True)
        return False
    finally:
        destination.close()
        source.close()


def _copy_into(database: Path, snapshot: Path) -> None:
    """Fallback snapshot: copy the database and its sidecars.

    Not consistent under a concurrent writer — the main file and the -wal are separate
    copies, so a checkpoint landing between them can produce a snapshot holding neither
    the checkpointed pages nor the WAL frames that carried them. Used only when the
    backup API could not open the source at all, where the alternative is not exporting.
    """
    shutil.copy2(database, snapshot)
    # The -wal holds visits Safari has committed but not yet checkpointed — usually
    # everything from the last few minutes. Skipping it is how an exporter ends up
    # missing the most recent browsing. Both sidecars are absent when Safari has
    # checkpointed cleanly, which is normal.
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, snapshot.with_name(snapshot.name + suffix))


@contextmanager
def _snapshot(database: Path) -> Iterator[Path]:
    """Take a private snapshot of the database and hand back its path.

    Safari runs History.db in WAL mode and holds it open all day. Reading it in place
    means either contending with those locks or opening it immutable and quietly missing
    everything still in the write-ahead log. A private snapshot cannot disturb Safari,
    and makes it impossible for a bug here to modify real history.
    """
    with tempfile.TemporaryDirectory(prefix="safari-history-export-") as workspace:
        snapshot = Path(workspace) / "History.db"
        try:
            if not _backup_into(database, snapshot):
                _copy_into(database, snapshot)
        except PermissionError as exc:
            raise FullDiskAccessRequired.for_path(database) from exc
        except OSError as exc:
            raise DatabaseUnreadable.snapshot_failed(database, str(exc)) from exc
        yield snapshot


def read_visits(
    day: date,
    database: Path = DEFAULT_DATABASE,
    *,
    require_fresh: bool = True,
) -> list[Visit]:
    """Every visit Safari recorded on `day`, in local time, oldest first."""
    _check_reachable(database)
    if require_fresh:
        _check_fresh_enough(database, day)
    start, end = day_bounds(day)

    with _snapshot(database) as snapshot:
        # Opened read-write even though nothing here writes. The backup API leaves a
        # snapshot with no -wal at all, but the copy fallback does not: recovering that
        # -wal is itself a write, and a read-only open of a WAL database fails when
        # SQLite cannot create its -shm. This is a throwaway copy either way, so letting
        # SQLite fix it up costs nothing and Safari's real file is untouched.
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
