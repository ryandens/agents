"""Failures that carry their own remediation.

These messages end up in a log file nobody reads until the export has been quietly
broken for a week, so each one says what failed, where, and what to do about it.
"Operation not permitted" on its own has cost enough people an afternoon.

Exit codes are distinct per failure class so a launchd log or a shell caller can tell
them apart without grepping message text.
"""

from __future__ import annotations

import sys
from pathlib import Path


class SafariHistoryError(Exception):
    """Base class: anything raised here is a failure with a message worth printing."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigurationError(SafariHistoryError):
    exit_code = 2


class FullDiskAccessRequired(SafariHistoryError):
    exit_code = 3

    @classmethod
    def for_path(cls, path: Path) -> FullDiskAccessRequired:
        # The grant is keyed to the executable that opens the file. For a Python
        # program that executable is the interpreter, not the script — naming the
        # script here would send someone to add a file macOS ignores.
        interpreter = Path(sys.executable).resolve()
        return cls(
            f"cannot read {path}: permission denied by macOS privacy protection (TCC).\n"
            "\n"
            "Safari's history is protected by Full Disk Access, which ordinary file\n"
            "permissions do not satisfy. Grant it to the interpreter running this tool:\n"
            "\n"
            "  1. System Settings -> Privacy & Security -> Full Disk Access\n"
            "  2. Click +, press Cmd-Shift-G, and enter:\n"
            f"       {interpreter}\n"
            "  3. Make sure its toggle is on, then run this command again.\n"
            "\n"
            "That path should be this tool's own dedicated virtualenv. If it points at a\n"
            "shared interpreter (Homebrew, python.org, /usr/bin/python3, or a uv cache),\n"
            "granting it would give every script run by that interpreter the same access\n"
            "-- see `export-safari-history status` and the install section of the README."
        )


class DatabaseMissing(SafariHistoryError):
    exit_code = 4

    @classmethod
    def for_path(cls, path: Path) -> DatabaseMissing:
        return cls(
            f"no Safari history database at {path}.\n"
            "\n"
            "Safari creates it on first use. If Safari is installed and has been used,\n"
            "check that this is the account that browses, or pass --database.\n"
            "\n"
            "macOS can also report a protected file as missing rather than as denied, so\n"
            "if the file is visibly there, treat this as a Full Disk Access problem."
        )


class DatabaseUnreadable(SafariHistoryError):
    exit_code = 5

    @classmethod
    def locked(cls, path: Path, detail: str) -> DatabaseUnreadable:
        return cls(
            f"{path} is locked by another process ({detail}).\n"
            "\n"
            "This is unusual: the exporter reads a private copy precisely so a running\n"
            "Safari cannot block it. Quitting Safari, or retrying once it has been idle\n"
            "for a moment, will clear it."
        )

    @classmethod
    def damaged(cls, path: Path, detail: str) -> DatabaseUnreadable:
        return cls(
            f"{path} could not be read as a SQLite database ({detail}).\n"
            "\n"
            "If Safari was mid-write when the copy was taken, the next run usually\n"
            "succeeds. If it keeps happening, the file may be damaged."
        )

    @classmethod
    def schema_changed(cls, detail: str) -> DatabaseUnreadable:
        return cls(
            f"the history query failed: {detail}.\n"
            "\n"
            "Safari's schema is not what this exporter expects, which usually means a\n"
            "macOS upgrade changed the history_visits or history_items tables."
        )

    @classmethod
    def snapshot_failed(cls, path: Path, detail: str) -> DatabaseUnreadable:
        return cls(
            f"could not copy {path} to a temporary working file: {detail}.\n"
            "\n"
            "The exporter never reads Safari's database in place, so it needs room in\n"
            "the temporary directory as well as permission to read the original."
        )


class DatabaseStale(DatabaseUnreadable):
    """Safari has not made the source current enough to prove a day was empty."""

    @classmethod
    def for_day(cls, path: Path, day: str, last_updated: str) -> DatabaseStale:
        return cls(
            f"Safari's history database at {path} was last updated {last_updated}, "
            f"before {day}.\n"
            "\n"
            "The exporter cannot treat an out-of-date database as proof that no "
            "browsing happened. Open Safari so it loads and syncs its history, then "
            "run the exporter again. This day was not marked as exported."
        )


class ExportFailed(SafariHistoryError):
    exit_code = 1


class UploadFailed(SafariHistoryError):
    exit_code = 6
