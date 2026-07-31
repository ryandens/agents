import builtins
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from safari_history import safari_db
from safari_history.errors import (
    DatabaseMissing,
    DatabaseUnreadable,
    FullDiskAccessRequired,
)
from safari_history.safari_db import (
    SAFARI_EPOCH_OFFSET,
    from_safari_time,
    read_visits,
    to_safari_time,
)
from tests.conftest import SCHEMA, FakeSafari

DAY = date(2026, 7, 29)


# --- Safari's timestamp convention ---


def test_the_epoch_offset_is_the_2001_reference_date() -> None:
    """The constant every hand-rolled version of this gets wrong by 31 years."""
    assert SAFARI_EPOCH_OFFSET == 978_307_200


def test_zero_is_january_2001() -> None:
    assert from_safari_time(0).astimezone(UTC) == datetime(2001, 1, 1, tzinfo=UTC)


def test_timestamps_round_trip() -> None:
    moment = datetime(2026, 7, 29, 8, 14, 22, tzinfo=UTC)
    assert from_safari_time(to_safari_time(moment)).astimezone(UTC) == moment


def test_sub_second_precision_is_dropped() -> None:
    """Truncation is what makes the API's (timestamp, url) dedup behave predictably."""
    moment = datetime(2026, 7, 29, 8, 14, 22, 987_654, tzinfo=UTC)
    assert from_safari_time(to_safari_time(moment)).microsecond == 0


def test_visits_are_returned_in_local_time() -> None:
    assert from_safari_time(0).utcoffset() is not None


# --- Day boundaries ---


def test_a_day_spans_exactly_one_day() -> None:
    start, end = safari_db.day_bounds(DAY)
    assert (end - start) / 3600 == pytest.approx(24, abs=1)


def test_visits_are_scoped_to_the_requested_day(safari: FakeSafari) -> None:
    safari.add_visit(
        DAY - timedelta(days=1), time(23, 59, 59), "https://before.example/"
    )
    safari.add_visit(DAY, time(0, 0, 0), "https://midnight.example/")
    safari.add_visit(DAY, time(23, 59, 59), "https://last.example/")
    safari.add_visit(DAY + timedelta(days=1), time(0, 0, 0), "https://after.example/")

    urls = [visit.url for visit in read_visits(DAY, database=safari.path)]
    assert urls == ["https://midnight.example/", "https://last.example/"]


def test_the_day_boundary_is_local_not_utc(safari: FakeSafari) -> None:
    """A late-evening visit belongs to the day it felt like, not to UTC's day."""
    safari.add_visit(DAY, time(23, 30), "https://late.example/")
    assert len(read_visits(DAY, database=safari.path)) == 1
    assert read_visits(DAY + timedelta(days=1), database=safari.path) == []


# --- Reading ---


def test_visits_come_back_oldest_first(safari: FakeSafari) -> None:
    safari.add_visit(DAY, time(18, 0), "https://evening.example/")
    safari.add_visit(DAY, time(9, 0), "https://morning.example/")

    urls = [visit.url for visit in read_visits(DAY, database=safari.path)]
    assert urls == ["https://morning.example/", "https://evening.example/"]


def test_a_null_title_becomes_empty(safari: FakeSafari) -> None:
    """Safari leaves the title null for a page it never got one for."""
    safari.add_visit(DAY, time(9, 0), "https://untitled.example/", title=None)
    assert read_visits(DAY, database=safari.path)[0].title == ""


def test_a_visit_with_no_history_item_is_dropped(safari: FakeSafari) -> None:
    safari.add_visit(DAY, time(9, 0), "https://real.example/")
    safari.add_orphan_visit(DAY, time(10, 0))
    assert len(read_visits(DAY, database=safari.path)) == 1


def test_an_empty_day_is_not_an_error(safari: FakeSafari) -> None:
    assert read_visits(DAY, database=safari.path) == []


def test_the_real_database_is_never_opened_for_writing(safari: FakeSafari) -> None:
    """Reading works even with the file read-only, which proves it is copied first."""
    safari.add_visit(DAY, time(9, 0), "https://a.example/")
    safari.path.chmod(0o400)
    try:
        assert len(read_visits(DAY, database=safari.path)) == 1
    finally:
        safari.path.chmod(0o600)


def test_visits_still_in_the_write_ahead_log_are_exported(tmp_path: Path) -> None:
    """The -wal is where the last few minutes of browsing live before a checkpoint."""
    database = tmp_path / "History.db"
    connection = sqlite3.connect(database)
    connection.executescript(SCHEMA)
    connection.execute("PRAGMA journal_mode=WAL")
    moment = datetime.combine(DAY, time(9, 0)).astimezone()
    connection.execute(
        "INSERT INTO history_items (id, url) VALUES (1, 'https://wal.example/')"
    )
    connection.execute(
        "INSERT INTO history_visits (id, history_item, visit_time, title) "
        "VALUES (1, 1, ?, 'In the WAL')",
        (to_safari_time(moment),),
    )
    connection.commit()
    # Left open on purpose: the -wal is not checkpointed back into the main file while
    # a connection holds it, which is exactly the state Safari is in all day.
    try:
        assert database.with_name("History.db-wal").exists()
        visits = read_visits(DAY, database=database)
        assert [visit.url for visit in visits] == ["https://wal.example/"]
    finally:
        connection.close()


# --- Failures ---


def test_a_missing_database_says_so(tmp_path: Path) -> None:
    with pytest.raises(DatabaseMissing) as caught:
        read_visits(DAY, database=tmp_path / "nope.db")
    assert caught.value.exit_code == 4
    assert "no Safari history database" in caught.value.message


def test_a_denied_read_names_full_disk_access(tmp_path: Path, monkeypatch) -> None:
    """The message has to name the interpreter, not the script — TCC keys on the binary."""
    database = tmp_path / "History.db"
    database.write_bytes(b"")

    # Scoped to this one file: a blanket open() failure would take pytest with it.
    real_open = builtins.open

    def deny(path, *args, **kwargs):
        if str(path) == str(database):
            raise PermissionError(1, "Operation not permitted")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny)

    with pytest.raises(FullDiskAccessRequired) as caught:
        read_visits(DAY, database=database)
    assert caught.value.exit_code == 3
    assert "Full Disk Access" in caught.value.message
    assert "System Settings" in caught.value.message


def test_a_file_that_is_not_a_database_says_so(tmp_path: Path) -> None:
    database = tmp_path / "History.db"
    database.write_text("this is not a database")
    with pytest.raises(DatabaseUnreadable) as caught:
        read_visits(DAY, database=database)
    assert caught.value.exit_code == 5


def test_a_changed_schema_is_reported_as_such(tmp_path: Path) -> None:
    """A macOS upgrade that renames a table needs a different fix from a corrupt file."""
    database = tmp_path / "History.db"
    sqlite3.connect(database).execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(DatabaseUnreadable) as caught:
        read_visits(DAY, database=database)
    assert "schema" in caught.value.message or "no such table" in caught.value.message
