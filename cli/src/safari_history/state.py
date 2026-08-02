"""What has already been exported, and what has already been uploaded.

Two independent records, deliberately. The export high-water mark says how far the
reader has got through the calendar; the upload ledger says which of those files the API
has acknowledged. Keeping them separate is what lets an API outage leave the exports
running and be repaired later by re-uploading, instead of stalling the whole pipeline
behind the network.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from safari_history.errors import ExportFailed

DEFAULT_STATE_FILE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "safari-history-export"
    / "state.json"
)


@dataclass
class Upload:
    digest: str
    visits: int
    uploaded_at: str


@dataclass
class State:
    path: Path
    last_exported_date: date | None = None
    uploads: dict[date, Upload] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path=path)
        # Everything that interprets the decoded JSON is inside the same guard as the
        # parse. Valid JSON of the wrong shape — a bare `[]`, a `last_exported_date` of
        # "bad", a non-mapping `uploads` — is exactly as unusable as a truncated file,
        # and reaches the user through the same message instead of an AttributeError or
        # a ValueError traceback with no hint that deleting the file is the way out.
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                # TypeError rather than ValueError because it is the shape that is
                # wrong, not the value; the handler below catches both alike.
                raise TypeError(f"expected a JSON object, found {type(raw).__name__}")

            last_exported = raw.get("last_exported_date")
            uploads = {}
            for day, entry in (raw.get("uploads") or {}).items():
                try:
                    uploads[date.fromisoformat(day)] = Upload(
                        digest=str(entry.get("digest", "")),
                        visits=int(entry.get("visits", 0)),
                        uploaded_at=str(entry.get("uploaded_at", "")),
                    )
                except AttributeError, TypeError, ValueError:
                    # One unreadable ledger entry means that day gets uploaded again.
                    # The API deduplicates, so the cost is a wasted request rather than
                    # duplicated data — much better than refusing to run at all.
                    continue

            return cls(
                path=path,
                last_exported_date=date.fromisoformat(last_exported)
                if last_exported
                else None,
                uploads=uploads,
            )
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            raise ExportFailed(
                f"the state file {path} could not be read: {exc}\n"
                "\n"
                "Delete it to start over — the next run will then export yesterday "
                "only, and re-upload any CSV it no longer has a record of."
            ) from exc

    def save(self) -> None:
        payload = {
            "last_exported_date": (
                self.last_exported_date.isoformat() if self.last_exported_date else None
            ),
            "updated_at": datetime.now(UTC).isoformat(),
            "uploads": {
                day.isoformat(): {
                    "digest": upload.digest,
                    "visits": upload.visits,
                    "uploaded_at": upload.uploaded_at,
                }
                for day, upload in sorted(self.uploads.items())
            },
        }

        # mkdir and mkstemp are inside the guard, not before it: a read-only or missing
        # parent directory fails here just as much as the write does, and it deserves
        # the same message rather than a bare OSError.
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            temporary = Path(raw_path)
            # Written aside and renamed: a truncated state file reads as "nothing has
            # ever been exported", which would re-export and re-upload from scratch.
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ExportFailed(
                f"the state file {self.path} could not be written: {exc}\n"
                "\n"
                "Any export this run made is still on disk, but the next run will "
                "repeat it."
            ) from exc
        finally:
            # None when mkdir or mkstemp is what failed, so there is nothing to remove.
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def record_upload(self, day: date, digest: str, visits: int) -> None:
        self.uploads[day] = Upload(
            digest=digest, visits=visits, uploaded_at=datetime.now(UTC).isoformat()
        )

    def needs_upload(self, day: date, digest: str) -> bool:
        """True if this day has never been uploaded, or its CSV changed since.

        Comparing digests rather than just presence means a day that was re-exported —
        after a fix, or a manual re-run — is sent again instead of being assumed done.
        """
        recorded = self.uploads.get(day)
        return recorded is None or recorded.digest != digest


def local_today() -> date:
    """Today in the machine's own zone.

    Explicitly local rather than `date.today()`, because every other date in this tool
    is anchored to local midnight; deriving the calendar from anything else would put
    the catch-up planner a day out from the exporter near midnight.
    """
    return datetime.now().astimezone().date()


def catch_up_days(last_exported: date | None, today: date, max_days: int) -> list[date]:
    """Which days still need exporting, oldest first.

    Never includes today, which is still being lived in: exporting it at 00:05 would
    capture five minutes of browsing and then mark the day done.
    """
    yesterday = today - timedelta(days=1)

    # No state: export yesterday alone. The alternative — everything Safari still
    # remembers, up to a year — is a surprising amount of work and network traffic to
    # trigger by installing something.
    if last_exported is None:
        return [yesterday]

    if last_exported >= yesterday:
        return []

    first_missing = last_exported + timedelta(days=1)
    # A machine that was off for months would otherwise try to export and upload every
    # one of those days in one run. This bounds any single run; the next one picks up
    # where this stopped.
    span = min((yesterday - first_missing).days + 1, max_days)
    return [first_missing + timedelta(days=offset) for offset in range(span)]
