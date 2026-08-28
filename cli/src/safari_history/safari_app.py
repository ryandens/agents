"""Briefly run Safari so its on-disk history catches up before an export."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from safari_history.errors import SafariRefreshFailed

_POLL_SECONDS = 0.25
_REFRESH_TIMEOUT_SECONDS = 15.0
_QUIT_TIMEOUT_SECONDS = 5.0
_SAFARI_EXECUTABLE = Path("/Applications/Safari.app/Contents/MacOS/Safari")


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


def _stop_owned_process(process: subprocess.Popen) -> SafariRefreshFailed | None:
    """Stop only the exact Safari process this exporter started."""
    if process.poll() is not None:
        return None
    process.terminate()
    try:
        process.wait(timeout=_QUIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except OSError as exc:
        return SafariRefreshFailed(
            f"Safari was opened to refresh history but could not be closed: {exc}"
        )
    return None


def refresh_history(
    database: Path,
    *,
    timeout: float = _REFRESH_TIMEOUT_SECONDS,
    poll_interval: float = _POLL_SECONDS,
) -> bool:
    """Refresh Safari history if closed; return whether this call launched it.

    Safari is launched as a directly-owned child process. That PID—not the application
    name—is terminated afterward, so a Safari the user starts concurrently is never
    mistaken for the exporter's instance. An already-running Safari is left alone.
    """
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
        process = subprocess.Popen(
            [str(_SAFARI_EXECUTABLE)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SafariRefreshFailed(
            f"could not open Safari to refresh history: {exc}"
        ) from exc

    failure: SafariRefreshFailed | None = None
    refreshed = False
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _source_mtime(database) > before:
                refreshed = True
                break
            time.sleep(poll_interval)
        if not refreshed:
            failure = SafariRefreshFailed(
                f"Safari's history database did not update within {timeout:g} seconds; "
                "the export was not advanced"
            )
    except OSError as exc:
        failure = SafariRefreshFailed(
            f"could not watch Safari's history database while refreshing: {exc}"
        )
    finally:
        stop_failure = _stop_owned_process(process)
        if failure is None:
            failure = stop_failure

    if failure is not None:
        raise failure
    return True
