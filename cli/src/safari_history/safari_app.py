"""Briefly run Safari so its on-disk history catches up before an export."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from safari_history.errors import SafariRefreshFailed

_POLL_SECONDS = 0.25
_REFRESH_TIMEOUT_SECONDS = 15.0


def _source_mtime(database: Path) -> float:
    sources = (database, database.with_name(database.name + "-wal"))
    return max((path.stat().st_mtime for path in sources if path.exists()), default=0)


def _is_running() -> bool:
    result = subprocess.run(
        ["/usr/bin/pgrep", "-x", "Safari"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SafariRefreshFailed("could not determine whether Safari is running")
    return result.returncode == 0


def refresh_history(
    database: Path,
    *,
    timeout: float = _REFRESH_TIMEOUT_SECONDS,
    poll_interval: float = _POLL_SECONDS,
) -> bool:
    """Refresh Safari history if Safari is closed; return whether it was launched.

    An already-running Safari is left entirely alone. When launched here, it is opened
    hidden and backgrounded, given time to load or sync history, and quit before the
    caller snapshots the database. Quitting encourages Safari to checkpoint its WAL.
    """
    # The CLI's database reader is intentionally portable so its real packaged command
    # can be smoke-tested against a synthetic SQLite database in Linux containers.
    # `open -a` and AppleScript are macOS application APIs; Linux may coincidentally
    # have /usr/bin/open, but it is a different command and must never be invoked here.
    if sys.platform != "darwin":
        return False

    if _is_running():
        return False

    try:
        before = _source_mtime(database)
    except OSError as exc:
        raise SafariRefreshFailed(
            f"could not inspect Safari's history database before refreshing: {exc}"
        ) from exc
    try:
        subprocess.run(
            ["/usr/bin/open", "-gj", "-a", "Safari"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SafariRefreshFailed(
            f"could not open Safari to refresh history: {exc}"
        ) from exc

    failure: SafariRefreshFailed | None = None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _source_mtime(database) > before:
                break
            time.sleep(poll_interval)
    except OSError as exc:
        failure = SafariRefreshFailed(
            f"could not watch Safari's history database while refreshing: {exc}"
        )
    finally:
        try:
            subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    'tell application "Safari" to quit',
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            if failure is None:
                failure = SafariRefreshFailed(
                    f"Safari was opened to refresh history but could not be closed: {exc}"
                )

    if failure is not None:
        raise failure
    return True
