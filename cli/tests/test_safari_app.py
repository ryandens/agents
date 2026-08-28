from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from safari_history import safari_app
from safari_history.errors import SafariRefreshFailed


def completed(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode)


def test_an_already_running_safari_is_left_alone(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return completed()

    monkeypatch.setattr(safari_app.subprocess, "run", run)

    assert safari_app.refresh_history(tmp_path / "History.db") is False
    assert calls == [["/usr/bin/pgrep", "-x", "Safari"]]


def test_a_closed_safari_is_opened_refreshed_and_closed(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "History.db"
    database.touch()
    calls: list[list[str]] = []
    mtimes = iter([1.0, 1.0, 2.0])

    def run(command, **kwargs):
        calls.append(command)
        return completed(1 if command[0] == "/usr/bin/pgrep" else 0)

    monkeypatch.setattr(safari_app.subprocess, "run", run)
    monkeypatch.setattr(safari_app, "_source_mtime", lambda path: next(mtimes))
    monkeypatch.setattr(safari_app.time, "monotonic", lambda: 0.0)

    assert safari_app.refresh_history(database, timeout=1, poll_interval=0) is True
    assert calls == [
        ["/usr/bin/pgrep", "-x", "Safari"],
        ["/usr/bin/open", "-gj", "-a", "Safari"],
        ["/usr/bin/osascript", "-e", 'tell application "Safari" to quit'],
    ]


def test_safari_is_closed_even_if_watching_the_database_fails(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "History.db"
    calls: list[list[str]] = []
    observations = 0

    def run(command, **kwargs):
        calls.append(command)
        return completed(1 if command[0] == "/usr/bin/pgrep" else 0)

    def mtime(path):
        nonlocal observations
        observations += 1
        if observations == 1:
            return 1.0
        raise OSError("denied")

    monkeypatch.setattr(safari_app.subprocess, "run", run)
    monkeypatch.setattr(safari_app, "_source_mtime", mtime)
    monkeypatch.setattr(safari_app.time, "monotonic", lambda: 0.0)

    with pytest.raises(SafariRefreshFailed, match="could not watch"):
        safari_app.refresh_history(database, timeout=1, poll_interval=0)

    assert calls[-1] == [
        "/usr/bin/osascript",
        "-e",
        'tell application "Safari" to quit',
    ]
