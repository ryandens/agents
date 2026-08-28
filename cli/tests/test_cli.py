"""End-to-end tests of the command line, against a synthetic Safari database.

Uploads are intercepted at `upload_visits`, so nothing here reaches Google or the API.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from safari_history import cli, csv_export
from safari_history.errors import UploadFailed
from safari_history.state import FIRST_EXPORT_DATE, State, local_today
from tests.conftest import FakeSafari


@pytest.fixture
def uploads(monkeypatch) -> list[dict]:
    """Records every upload the CLI attempts, and never fails."""
    recorded: list[dict] = []

    def fake_upload(visits, *, api_url, token, batch_size=500, session=None):
        recorded.append({"api_url": api_url, "token": token, "visits": list(visits)})
        return {"received": len(visits), "stored": len(visits)}

    monkeypatch.setattr(cli, "upload_visits", fake_upload)
    monkeypatch.setattr(cli, "mint_id_token", lambda key, audience: "test-token")
    return recorded


@pytest.fixture
def caught_up(workspace) -> date:
    """Seeds the export mark so a bare run covers exactly yesterday, and returns it.

    Most tests here are about what happens to a single day — it uploads, it retries, it
    shows up in `status` — not about where a fresh install begins. Without this they
    would each plan the whole backfill from FIRST_EXPORT_DATE and assert against a
    span that grows by a day every day.
    """
    yesterday = local_today() - timedelta(days=1)
    state = State.load(workspace["state_file"])
    state.last_exported_date = yesterday - timedelta(days=1)
    state.save()
    return yesterday


@pytest.fixture
def workspace(tmp_path: Path, safari: FakeSafari, monkeypatch) -> dict:
    monkeypatch.setattr(cli.safari_app, "refresh_history", lambda database: False)
    key = tmp_path / "service-account.json"
    key.write_text("{}")
    return {
        "export_dir": tmp_path / "exports",
        "state_file": tmp_path / "state.json",
        "database": safari.path,
        "key": key,
        "safari": safari,
    }


def run(workspace: dict, *args: str, upload: bool = True) -> int:
    argv = [
        *args,
        "--export-dir",
        str(workspace["export_dir"]),
        "--state-file",
        str(workspace["state_file"]),
    ]
    if upload:
        argv += [
            "--api-url",
            "https://agents.example.com/api/browser-history",
            "--service-account-file",
            str(workspace["key"]),
        ]
    if args and args[0] in ("export", "status") or not args or args[0][0].isdigit():
        argv += ["--database", str(workspace["database"])]
    return cli.main(argv)


# --- Exporting a named day ---


def test_exporting_a_named_day_writes_the_csv(workspace, uploads) -> None:
    day = date(2026, 7, 29)
    workspace["safari"].add_visit(day, time(9, 0), "https://example.com/", "Example")

    assert run(workspace, day.isoformat()) == 0

    written = workspace["export_dir"] / "Safari History - 2026-07-29.csv"
    assert written.exists()
    assert "https://example.com/" in written.read_text()


def test_the_bare_date_form_works(workspace, uploads) -> None:
    """The documented interface: `export-safari-history YYYY-MM-DD`, no subcommand."""
    day = date(2026, 7, 29)
    workspace["safari"].add_visit(day, time(9, 0), "https://example.com/")
    assert run(workspace, "2026-07-29") == 0
    assert (workspace["export_dir"] / "Safari History - 2026-07-29.csv").exists()


def test_a_named_day_does_not_move_the_high_water_mark(workspace, uploads) -> None:
    """Re-exporting an old day is a repair job, not progress through the calendar."""
    run(workspace, "2026-07-29")
    assert State.load(workspace["state_file"]).last_exported_date is None


def test_an_invalid_date_is_a_usage_error(workspace, capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        run(workspace, "yesterday")
    assert caught.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


# --- Catching up ---


def test_the_bare_command_backfills_from_the_start_date(workspace, uploads) -> None:
    """With no state, the catch-up begins at the fixed start date, oldest day first."""
    workspace["safari"].add_visit(FIRST_EXPORT_DATE, time(9, 0), "https://example.com/")

    assert run(workspace) == 0

    written = workspace["export_dir"] / csv_export.file_name(FIRST_EXPORT_DATE)
    assert "https://example.com/" in written.read_text()
    assert min(csv_export.exported_days(workspace["export_dir"])) == FIRST_EXPORT_DATE


def test_missed_days_are_caught_up(workspace, uploads) -> None:
    """The Mac was off for three days."""
    today = local_today()
    state = State.load(workspace["state_file"])
    state.last_exported_date = today - timedelta(days=4)
    state.save()

    for offset in range(1, 4):
        workspace["safari"].add_visit(
            today - timedelta(days=offset), time(9, 0), f"https://day{offset}.example/"
        )

    assert run(workspace) == 0

    exported = csv_export.exported_days(workspace["export_dir"])
    assert len(exported) == 3
    assert State.load(workspace["state_file"]).last_exported_date == today - timedelta(
        days=1
    )


def test_a_second_run_does_nothing(workspace, uploads, caught_up) -> None:
    run(workspace)
    before = len(uploads)
    assert run(workspace) == 0
    assert len(uploads) == before


def test_a_day_with_no_browsing_still_exports(workspace, uploads, caught_up) -> None:
    """Otherwise a quiet day blocks the high-water mark forever."""
    yesterday = caught_up
    assert run(workspace) == 0

    written = workspace["export_dir"] / csv_export.file_name(yesterday)
    assert written.read_text() == "visited_at,title,url\n"
    assert State.load(workspace["state_file"]).last_exported_date == yesterday


def test_a_stale_database_does_not_write_or_advance_the_export_mark(
    workspace, uploads, caught_up, capsys
) -> None:
    stale = (
        datetime.combine(caught_up - timedelta(days=1), time(12))
        .astimezone()
        .timestamp()
    )
    os.utime(workspace["database"], (stale, stale))

    assert run(workspace) == 5

    assert not (workspace["export_dir"] / csv_export.file_name(caught_up)).exists()
    assert State.load(
        workspace["state_file"]
    ).last_exported_date == caught_up - timedelta(days=1)
    assert uploads == []
    assert "Open Safari" in capsys.readouterr().err


# --- Uploading ---


def test_an_export_uploads_what_it_wrote(workspace, uploads, caught_up) -> None:
    yesterday = caught_up
    workspace["safari"].add_visit(
        yesterday, time(9, 0), "https://example.com/", "Example"
    )

    run(workspace)

    assert len(uploads) == 1
    assert uploads[0]["visits"] == [
        {
            "timestamp": uploads[0]["visits"][0]["timestamp"],
            "url": "https://example.com/",
            "title": "Example",
        }
    ]


def test_no_upload_writes_nothing_to_the_network(workspace, uploads, caught_up) -> None:
    assert run(workspace, "export", "--no-upload", upload=False) == 0
    assert uploads == []


def test_an_upload_failure_does_not_lose_the_export(
    workspace, monkeypatch, caught_up
) -> None:
    """The CSV stays on disk and the day stays pending, ready for `upload`."""
    yesterday = caught_up
    workspace["safari"].add_visit(yesterday, time(9, 0), "https://example.com/")

    monkeypatch.setattr(cli, "mint_id_token", lambda key, audience: "test-token")
    monkeypatch.setattr(
        cli,
        "upload_visits",
        lambda *args, **kwargs: (_ for _ in ()).throw(UploadFailed("the API is down")),
    )

    assert run(workspace) == 1
    assert (workspace["export_dir"] / csv_export.file_name(yesterday)).exists()
    # The export mark still advanced: exporting worked, only the upload did not.
    assert State.load(workspace["state_file"]).last_exported_date == yesterday
    assert State.load(workspace["state_file"]).uploads == {}


def test_upload_retries_what_the_api_never_acknowledged(
    workspace, uploads, monkeypatch, caught_up
) -> None:
    yesterday = caught_up
    workspace["safari"].add_visit(yesterday, time(9, 0), "https://example.com/")

    monkeypatch.setattr(
        cli,
        "upload_visits",
        lambda *args, **kwargs: (_ for _ in ()).throw(UploadFailed("the API is down")),
    )
    monkeypatch.setattr(cli, "mint_id_token", lambda key, audience: "test-token")
    run(workspace)

    monkeypatch.undo()
    monkeypatch.setattr(cli, "mint_id_token", lambda key, audience: "test-token")
    recorded: list = []
    monkeypatch.setattr(
        cli,
        "upload_visits",
        lambda visits, **kwargs: (
            recorded.append(visits) or {"received": 1, "stored": 1}
        ),
    )

    assert run(workspace, "upload") == 0
    assert len(recorded) == 1


def test_upload_skips_days_the_api_already_has(workspace, uploads, caught_up) -> None:
    run(workspace)
    before = len(uploads)
    assert run(workspace, "upload") == 0
    assert len(uploads) == before


def test_a_named_day_is_always_re_uploaded(workspace, uploads, caught_up) -> None:
    """An explicit `upload 2026-07-29` is a repair, so it re-sends unconditionally."""
    yesterday = caught_up
    run(workspace)
    before = len(uploads)
    assert run(workspace, "upload", yesterday.isoformat()) == 0
    assert len(uploads) == before + 1


def test_a_re_exported_day_is_uploaded_again(workspace, uploads, caught_up) -> None:
    yesterday = caught_up
    run(workspace)
    before = len(uploads)

    workspace["safari"].add_visit(yesterday, time(10, 0), "https://later.example/")
    run(workspace, yesterday.isoformat())

    assert len(uploads) == before + 1


def test_dry_run_sends_nothing(workspace, uploads) -> None:
    run(workspace, "export", "--no-upload", upload=False)
    assert run(workspace, "upload", "--dry-run") == 0
    assert uploads == []


def test_upload_without_an_api_url_explains_itself(
    workspace, capsys, monkeypatch
) -> None:
    # `just` loads the repository's .env before running pytest. This test is about the
    # missing-configuration path, so make that precondition explicit and deterministic.
    monkeypatch.delenv("SAFARI_HISTORY_API_URL", raising=False)
    run(workspace, "export", "--no-upload", upload=False)
    assert (
        cli.main(
            [
                "upload",
                "--export-dir",
                str(workspace["export_dir"]),
                "--state-file",
                str(workspace["state_file"]),
            ]
        )
        == 2
    )
    assert "SAFARI_HISTORY_API_URL" in capsys.readouterr().err


def test_uploading_a_day_with_no_csv_is_an_error(workspace, uploads, capsys) -> None:
    assert run(workspace, "upload", "2026-07-29") == 1
    assert "export it first" in capsys.readouterr().err


def test_one_missing_day_does_not_abandon_the_others(workspace, uploads) -> None:
    """Naming four days to repair, one of them a typo, must still repair the rest."""
    yesterday = local_today() - timedelta(days=1)
    run(workspace, "export", "--no-upload", upload=False)
    before = len(uploads)

    assert run(workspace, "upload", "2026-07-29", yesterday.isoformat()) == 1
    assert len(uploads) == before + 1


# --- Failures ---


def test_a_missing_database_exits_four(workspace, uploads, tmp_path, capsys) -> None:
    workspace["database"] = tmp_path / "gone.db"
    assert run(workspace, "2026-07-29") == 4
    assert "no Safari history database" in capsys.readouterr().err


def test_a_denied_database_exits_three(workspace, uploads, monkeypatch, capsys) -> None:
    import builtins

    real_open = builtins.open
    target = str(workspace["database"])

    def deny(path, *args, **kwargs):
        if str(path) == target:
            raise PermissionError(1, "Operation not permitted")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny)
    assert run(workspace, "2026-07-29") == 3
    assert "Full Disk Access" in capsys.readouterr().err


# --- Status ---


def test_status_names_the_interpreter_to_grant(workspace, capsys) -> None:
    import sys

    assert run(workspace, "status") == 0
    output = capsys.readouterr().out
    assert "needs Full Disk Access" in output
    assert str(Path(sys.executable).resolve()) in output


def test_status_reports_a_stale_but_valid_database_as_readable(
    workspace, capsys
) -> None:
    stale = (
        datetime.combine(local_today() - timedelta(days=1), time(12))
        .astimezone()
        .timestamp()
    )
    os.utime(workspace["database"], (stale, stale))

    assert run(workspace, "status") == 0
    output = capsys.readouterr().out
    assert "  readable" in output
    assert "NOT READABLE" not in output


def test_status_reports_pending_uploads(workspace, uploads, capsys, caught_up) -> None:
    run(workspace, "export", "--no-upload", upload=False)
    capsys.readouterr()
    run(workspace, "status")
    assert "pending upload: 1" in capsys.readouterr().out


# --- Argument validation (Macroscope review) ---


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_non_positive_catchup_cap_is_a_usage_error(workspace, capsys, value) -> None:
    """Silently exporting nothing and exiting 0 reads as "already up to date"."""
    with pytest.raises(SystemExit) as caught:
        run(workspace, "export", "--max-catchup-days", value, upload=False)
    assert caught.value.code == 2
    assert "at least 1" in capsys.readouterr().err


def test_a_positive_catchup_cap_is_accepted(workspace, uploads) -> None:
    assert (
        run(
            workspace,
            "export",
            "--no-upload",
            "--max-catchup-days",
            "1",
            upload=False,
        )
        == 0
    )
