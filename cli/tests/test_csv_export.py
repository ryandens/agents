import csv
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from safari_history import csv_export
from safari_history.errors import ExportFailed
from safari_history.safari_db import Visit

DAY = date(2026, 7, 29)


def visit(title: str = "Example Domain", url: str = "https://example.com/") -> Visit:
    return Visit(
        visited_at=datetime.fromisoformat("2026-07-29T08:14:22-04:00"),
        title=title,
        url=url,
    )


# --- Naming ---


def test_file_name_matches_the_documented_format() -> None:
    assert csv_export.file_name(DAY) == "Safari History - 2026-07-29.csv"


def test_names_round_trip() -> None:
    assert csv_export.day_from_file_name(csv_export.file_name(DAY)) == DAY


@pytest.mark.parametrize(
    "name",
    [
        "Safari History - notes.csv",
        "Safari History - 2026-07-29 copy.csv",
        "Safari History - 2026-07-29.csv.tmp",
        ".Safari History - 2026-07-29.csv.1234.tmp",
        "something-else.csv",
    ],
)
def test_files_that_are_not_exports_are_ignored(name: str) -> None:
    """A Finder duplicate or an in-flight temp file must never be uploaded."""
    assert csv_export.day_from_file_name(name) is None


def test_an_impossible_date_in_the_name_is_ignored() -> None:
    assert csv_export.day_from_file_name("Safari History - 2026-13-45.csv") is None


def test_exported_days_finds_only_exports(tmp_path: Path) -> None:
    csv_export.write_csv([visit()], tmp_path / csv_export.file_name(DAY))
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / ".Safari History - 2026-07-28.csv.99.tmp").write_text("partial")

    assert list(csv_export.exported_days(tmp_path)) == [DAY]


def test_exported_days_on_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert csv_export.exported_days(tmp_path / "nope") == {}


# --- Writing ---


def test_the_header_is_the_documented_one(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([], destination)
    assert destination.read_text() == "visited_at,title,url\n"


def test_an_empty_day_still_writes_a_file(tmp_path: Path) -> None:
    """Header-only says "exported and empty"; a missing file says "never exported"."""
    destination = tmp_path / "out.csv"
    csv_export.write_csv([], destination)
    assert destination.exists()


def test_a_row_holds_the_local_timestamp_title_and_url(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit()], destination)
    assert destination.read_text().splitlines()[1] == (
        "2026-07-29T08:14:22-04:00,Example Domain,https://example.com/"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ruby, Rails and rest", '"Ruby, Rails and rest"'),
        ('The "Best" Page', '"The ""Best"" Page"'),
        ("Two\nLines", '"Two\nLines"'),
    ],
)
def test_titles_that_would_corrupt_the_columns_are_quoted(
    tmp_path: Path, title: str, expected: str
) -> None:
    """An unquoted comma in a title silently shifts the url into the wrong column."""
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit(title=title)], destination)
    assert expected in destination.read_text()


def test_quoted_titles_survive_the_round_trip(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit(title='Comma, and "quotes"')], destination)
    assert csv_export.read_csv(destination)[0]["title"] == 'Comma, and "quotes"'


def test_the_directory_is_created(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "deeper" / "out.csv"
    csv_export.write_csv([visit()], destination)
    assert destination.exists()


def test_writing_leaves_no_temporary_files(tmp_path: Path) -> None:
    csv_export.write_csv([visit()], tmp_path / "out.csv")
    assert [path.name for path in tmp_path.iterdir()] == ["out.csv"]


def test_a_failed_write_leaves_no_partial_file(tmp_path: Path, monkeypatch) -> None:
    """The requirement: an interrupted export must not leave a truncated CSV behind."""
    destination = tmp_path / "out.csv"

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(csv_export.os, "replace", explode)

    with pytest.raises(ExportFailed):
        csv_export.write_csv([visit()], destination)

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_re_exporting_a_day_replaces_it(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit(), visit(url="https://second.example/")], destination)
    csv_export.write_csv([visit()], destination)
    assert len(csv_export.read_csv(destination)) == 1


# --- Reading back ---


def test_read_csv_shapes_rows_for_the_api(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit()], destination)
    assert csv_export.read_csv(destination) == [
        {
            "timestamp": "2026-07-29T08:14:22-04:00",
            "url": "https://example.com/",
            "title": "Example Domain",
        }
    ]


def test_read_csv_rejects_a_foreign_file(tmp_path: Path) -> None:
    foreign = tmp_path / "out.csv"
    foreign.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ExportFailed, match="does not look like an export"):
        csv_export.read_csv(foreign)


def test_read_csv_rejects_timestamps_without_an_offset(tmp_path: Path) -> None:
    """Without an offset the API cannot tell which local day a visit belongs to."""
    naive = tmp_path / "out.csv"
    naive.write_text(
        "visited_at,title,url\n2026-07-29T23:40:00,Late,https://a.example/\n"
    )
    with pytest.raises(ExportFailed, match="no UTC offset"):
        csv_export.read_csv(naive)


def test_the_digest_changes_when_the_export_does(tmp_path: Path) -> None:
    destination = tmp_path / "out.csv"
    csv_export.write_csv([visit()], destination)
    before = csv_export.digest(destination)
    csv_export.write_csv([visit(), visit(url="https://new.example/")], destination)
    assert csv_export.digest(destination) != before


# --- Damaged exports (Macroscope review) ---
#
# The upload sweep counts a failed day and carries on to the rest. Anything that escapes
# as a bare OSError/UnicodeDecodeError/csv.Error breaks that contract by killing the
# whole run, so each of these has to surface as ExportFailed.


def test_a_digest_of_a_missing_file_is_reported(tmp_path: Path) -> None:
    """The file can vanish between the directory scan and the hash."""
    with pytest.raises(ExportFailed, match="could not read"):
        csv_export.digest(tmp_path / "Safari History - 2026-07-29.csv")


def test_reading_a_non_utf8_export_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "Safari History - 2026-07-29.csv"
    path.write_bytes(
        b"visited_at,title,url\n2026-07-29T09:00:00-04:00,\xff\xfe,http://a/\n"
    )
    with pytest.raises(ExportFailed, match="could not read"):
        csv_export.read_csv(path)


def test_reading_an_export_with_an_oversized_field_is_reported(tmp_path: Path) -> None:
    """csv.Error, not OSError — a different escape from the same function."""
    path = tmp_path / "Safari History - 2026-07-29.csv"
    huge = "a" * (csv.field_size_limit() + 1)
    path.write_text(
        f'visited_at,title,url\n2026-07-29T09:00:00-04:00,"{huge}",http://a/\n'
    )
    with pytest.raises(ExportFailed, match="could not read"):
        csv_export.read_csv(path)


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores the mode bits, so the read would succeed"
)
def test_an_unreadable_export_directory_is_reported(tmp_path: Path) -> None:
    """Not an empty result: that would read as "nothing to upload"."""
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "Safari History - 2026-07-29.csv").write_text(
        "visited_at,title,url\n"
    )
    export_dir.chmod(0o000)
    try:
        with pytest.raises(ExportFailed, match="could not read"):
            csv_export.exported_days(export_dir)
    finally:
        export_dir.chmod(0o755)
