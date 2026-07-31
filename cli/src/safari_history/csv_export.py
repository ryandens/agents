"""Writing and reading the per-day CSV files."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from safari_history.errors import ExportFailed
from safari_history.safari_db import Visit

DEFAULT_EXPORT_DIR = Path.home() / "Safari-History-Exports"

HEADER = ["visited_at", "title", "url"]

_FILE_NAME = "Safari History - {day}.csv"
# Anchored, and strict about the digits, so a stray "Safari History - notes.csv" or a
# Finder duplicate ("... copy.csv") is not mistaken for an export and uploaded.
_FILE_PATTERN = re.compile(r"^Safari History - (\d{4}-\d{2}-\d{2})\.csv$")


def file_name(day: date) -> str:
    return _FILE_NAME.format(day=day.isoformat())


def day_from_file_name(name: str) -> date | None:
    match = _FILE_PATTERN.match(name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def exported_days(export_dir: Path) -> dict[date, Path]:
    """Every day that has a CSV on disk, by date."""
    if not export_dir.is_dir():
        return {}
    found = {}
    for path in export_dir.iterdir():
        day = day_from_file_name(path.name)
        if day is not None and path.is_file():
            found[day] = path
    return dict(sorted(found.items()))


def write_csv(visits: Iterable[Visit], destination: Path) -> None:
    """Write the day's visits, atomically.

    The uploader reads this directory, so it must never see a half-written file under
    its final name. The temporary file is a sibling rather than something in /tmp so
    that os.replace is a rename within one filesystem, which is atomic; across
    filesystems it degrades into a copy and loses the guarantee. The dot prefix keeps
    the partial file out of Finder and out of the uploader's scan for the moment it
    exists, and it is removed on every failure path, so nothing is left behind.

    mkstemp also creates the file 0600, and the rename carries that through to the
    export. A list of everywhere someone browsed should not land in a shared directory
    world-readable because of an inherited umask.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor, raw_path = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            # QUOTE_MINIMAL with the default dialect is RFC 4180: quote only when the
            # value contains a comma, quote, or newline, and double any embedded quotes.
            # Page titles really do contain all three, and an unquoted title with a
            # comma silently shifts the url into the wrong column.
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(HEADER)
            for visit in visits:
                writer.writerow([visit.visited_at.isoformat(), visit.title, visit.url])
            handle.flush()
            # A rename is atomic, but only with respect to data that has reached the
            # disk. Without this, a power loss just after the rename can leave a
            # correctly-named, empty file.
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        raise ExportFailed(f"could not write {destination}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a day's CSV back as SiteVisit-shaped dicts, ready to post."""
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != HEADER:
                raise ExportFailed(
                    f"{path} does not look like an export: expected columns "
                    f"{','.join(HEADER)}, found {','.join(reader.fieldnames or [])}"
                )
            rows = [
                {
                    "timestamp": row["visited_at"],
                    "url": row["url"],
                    "title": row["title"] or "",
                }
                for row in reader
                if row.get("url")
            ]
    except OSError as exc:
        raise ExportFailed(f"could not read {path}: {exc}") from exc

    for row in rows:
        # Caught here rather than at the API, where it would come back as a 422 for a
        # whole batch with no indication of which row or file caused it.
        try:
            moment = datetime.fromisoformat(row["timestamp"])
        except ValueError as exc:
            raise ExportFailed(
                f"{path}: '{row['timestamp']}' is not a timestamp this tool wrote"
            ) from exc
        if moment.utcoffset() is None:
            raise ExportFailed(
                f"{path}: '{row['timestamp']}' has no UTC offset, so the day it belongs "
                "to is ambiguous — re-export this day"
            )
    return rows


def digest(path: Path) -> str:
    """A content hash, so a re-exported day can be recognised and re-uploaded."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
