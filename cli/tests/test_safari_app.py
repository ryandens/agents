from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from safari_history import safari_app
from safari_history.errors import SafariRefreshFailed


class Process:
    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout=None) -> int:
        return 0


def completed(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode)


@pytest.fixture(autouse=True)
def macos(monkeypatch) -> None:
    monkeypatch.setattr(safari_app.sys, "platform", "darwin")


def test_non_macos_runs_do_not_try_to_control_an_application(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(safari_app.sys, "platform", "linux")
    monkeypatch.setattr(
        safari_app.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess should not be called"),
    )
    assert safari_app.refresh_history(tmp_path / "History.db") is False


def test_an_already_running_safari_is_left_alone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        safari_app.subprocess, "run", lambda *args, **kwargs: completed()
    )
    monkeypatch.setattr(
        safari_app.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Safari should not be launched"),
    )
    assert safari_app.refresh_history(tmp_path / "History.db") is False


def test_a_closed_safari_is_refreshed_and_only_the_owned_process_is_stopped(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "History.db"
    process = Process()
    mtimes = iter([1.0, 1.0, 2.0])
    monkeypatch.setattr(
        safari_app.subprocess, "run", lambda *args, **kwargs: completed(1)
    )
    monkeypatch.setattr(safari_app.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(safari_app, "_source_mtime", lambda path: next(mtimes))
    monkeypatch.setattr(safari_app.time, "monotonic", lambda: 0.0)

    assert safari_app.refresh_history(database, timeout=1, poll_interval=0) is True
    assert process.terminated is True
    assert process.killed is False


def test_a_refresh_timeout_fails_and_stops_the_owned_process(
    tmp_path: Path, monkeypatch
) -> None:
    process = Process()
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(
        safari_app.subprocess, "run", lambda *args, **kwargs: completed(1)
    )
    monkeypatch.setattr(safari_app.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(safari_app, "_source_mtime", lambda path: 1.0)
    monkeypatch.setattr(safari_app.time, "monotonic", lambda: next(clock))

    with pytest.raises(SafariRefreshFailed, match="did not update within 1 seconds"):
        safari_app.refresh_history(tmp_path / "History.db", timeout=1, poll_interval=0)
    assert process.terminated is True


def test_the_owned_process_is_stopped_if_watching_the_database_fails(
    tmp_path: Path, monkeypatch
) -> None:
    process = Process()
    observations = 0

    def mtime(path):
        nonlocal observations
        observations += 1
        if observations == 1:
            return 1.0
        raise OSError("denied")

    monkeypatch.setattr(
        safari_app.subprocess, "run", lambda *args, **kwargs: completed(1)
    )
    monkeypatch.setattr(safari_app.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(safari_app, "_source_mtime", mtime)
    monkeypatch.setattr(safari_app.time, "monotonic", lambda: 0.0)

    with pytest.raises(SafariRefreshFailed, match="could not watch"):
        safari_app.refresh_history(tmp_path / "History.db", timeout=1, poll_interval=0)
    assert process.terminated is True
