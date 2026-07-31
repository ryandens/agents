from datetime import date, timedelta
from pathlib import Path

import pytest

from safari_history.errors import ExportFailed
from safari_history.state import State, catch_up_days

TODAY = date(2026, 7, 30)
YESTERDAY = date(2026, 7, 29)


# --- Catch-up planning ---


def test_a_first_run_exports_yesterday_only() -> None:
    """Not a year of history: installing something should not trigger a huge backfill."""
    assert catch_up_days(None, TODAY, max_days=30) == [YESTERDAY]


def test_today_is_never_exported() -> None:
    """It is still being lived in — 00:15 would capture 15 minutes and call it done."""
    assert TODAY not in catch_up_days(None, TODAY, max_days=30)
    assert TODAY not in catch_up_days(date(2026, 7, 1), TODAY, max_days=30)


def test_nothing_to_do_when_already_current() -> None:
    assert catch_up_days(YESTERDAY, TODAY, max_days=30) == []


def test_a_mark_ahead_of_yesterday_asks_for_nothing() -> None:
    """A clock change or a hand-edited state file must not produce negative work."""
    assert catch_up_days(TODAY, TODAY, max_days=30) == []
    assert catch_up_days(TODAY + timedelta(days=5), TODAY, max_days=30) == []


def test_missed_days_are_caught_up_oldest_first() -> None:
    """The laptop was shut on the 26th and opened on the 30th."""
    assert catch_up_days(date(2026, 7, 25), TODAY, max_days=30) == [
        date(2026, 7, 26),
        date(2026, 7, 27),
        date(2026, 7, 28),
        date(2026, 7, 29),
    ]


def test_a_long_absence_is_capped_per_run() -> None:
    days = catch_up_days(date(2025, 1, 1), TODAY, max_days=30)
    assert len(days) == 30
    assert days[0] == date(2025, 1, 2)


def test_the_cap_resumes_where_it_stopped() -> None:
    first = catch_up_days(date(2026, 6, 1), TODAY, max_days=10)
    second = catch_up_days(first[-1], TODAY, max_days=10)
    assert second[0] == first[-1] + timedelta(days=1)


def test_a_month_boundary_is_handled() -> None:
    assert catch_up_days(date(2026, 6, 29), date(2026, 7, 2), max_days=30) == [
        date(2026, 6, 30),
        date(2026, 7, 1),
    ]


# --- Persistence ---


def test_a_missing_state_file_reads_as_empty(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    assert state.last_exported_date is None
    assert state.uploads == {}


def test_state_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.json"
    state = State.load(path)
    state.last_exported_date = YESTERDAY
    state.record_upload(YESTERDAY, digest="abc123", visits=42)
    state.save()

    reloaded = State.load(path)
    assert reloaded.last_exported_date == YESTERDAY
    assert reloaded.uploads[YESTERDAY].digest == "abc123"
    assert reloaded.uploads[YESTERDAY].visits == 42


def test_a_corrupt_state_file_explains_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(ExportFailed, match="Delete it to start over"):
        State.load(path)


def test_one_bad_ledger_entry_does_not_block_the_run(tmp_path: Path) -> None:
    """Re-uploading a day is cheap; refusing to run at all is not."""
    path = tmp_path / "state.json"
    path.write_text(
        '{"last_exported_date": "2026-07-29", '
        '"uploads": {"2026-07-28": {"digest": "ok", "visits": 1, "uploaded_at": ""}, '
        '"not-a-date": {"digest": "x"}}}'
    )
    state = State.load(path)
    assert list(state.uploads) == [date(2026, 7, 28)]


def test_saving_leaves_no_temporary_files(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    state.last_exported_date = YESTERDAY
    state.save()
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


# --- Upload ledger ---


def test_an_unknown_day_needs_uploading(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    assert state.needs_upload(YESTERDAY, "abc123")


def test_an_unchanged_day_does_not(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    state.record_upload(YESTERDAY, digest="abc123", visits=1)
    assert not state.needs_upload(YESTERDAY, "abc123")


def test_a_re_exported_day_is_sent_again(tmp_path: Path) -> None:
    """A day fixed and re-exported must not be assumed done."""
    state = State.load(tmp_path / "state.json")
    state.record_upload(YESTERDAY, digest="abc123", visits=1)
    assert state.needs_upload(YESTERDAY, "different")
