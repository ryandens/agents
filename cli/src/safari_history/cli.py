"""Command line entry point.

export-safari-history                 catch up: every day since the last export
export-safari-history 2026-07-29      one specific day
export-safari-history upload          re-send anything the API has not acknowledged
export-safari-history status          what is installed, granted, and pending
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

from safari_history import csv_export, safari_db
from safari_history.errors import ConfigurationError, SafariHistoryError
from safari_history.state import (
    DEFAULT_STATE_FILE,
    State,
    catch_up_days,
    local_today,
)
from safari_history.uploader import default_audience, mint_id_token, upload_visits

SUBCOMMANDS = ("export", "upload", "status")

DEFAULT_MAX_CATCHUP_DAYS = 30

EXIT_CODES = """\
exit codes:
  0  success                       4  history database not found
  1  export or state failure       5  history database unreadable or locked
  2  bad arguments                 6  upload or credential failure
  3  Full Disk Access required
"""


def _log(message: str) -> None:
    """Timestamped, because this is a log file that accumulates for months.

    A line without a timestamp cannot answer "did last night's run happen?", which is
    the only question anyone asks of it.
    """
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}")


def _log_error(message: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{stamp}] error: {message}", file=sys.stderr)


def _valid_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a date — expected YYYY-MM-DD, e.g. 2026-07-29"
        ) from None


def _positive_days(text: str) -> int:
    """A day count of at least 1.

    Rejected at the boundary rather than clamped: `--max-catchup-days 0` asks for a run
    that cannot make progress, and silently treating it as 1 would export a day the
    caller explicitly asked not to. Without this the run exits 0 having done nothing,
    which reads as "already up to date".
    """
    try:
        days = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number") from None
    if days < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 1, got {days} — a run capped at {days} days would "
            "report success without exporting anything"
        )
    return days


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export-safari-history",
        description=(
            "Export Safari browsing history to one CSV per day and post it to the API. "
            "Private Browsing is never exported: Safari does not record it."
        ),
        epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--export-dir",
            type=Path,
            default=Path(
                os.environ.get(
                    "SAFARI_HISTORY_EXPORT_DIR", csv_export.DEFAULT_EXPORT_DIR
                )
            ),
            help="where CSVs are written (default: ~/Safari-History-Exports)",
        )
        target.add_argument(
            "--state-file",
            type=Path,
            default=Path(
                os.environ.get("SAFARI_HISTORY_STATE_FILE", DEFAULT_STATE_FILE)
            ),
            help="catch-up and upload bookkeeping (default: ~/Library/Application "
            "Support/safari-history-export/state.json)",
        )
        target.add_argument(
            "--api-url",
            default=os.environ.get("SAFARI_HISTORY_API_URL", ""),
            help="full URL of the browser-history endpoint, e.g. "
            "https://agents.example.com/api/browser-history "
            "(env: SAFARI_HISTORY_API_URL)",
        )
        target.add_argument(
            "--service-account-file",
            type=Path,
            default=Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            else None,
            help="service account JSON key (env: GOOGLE_APPLICATION_CREDENTIALS)",
        )
        target.add_argument(
            "--audience",
            default=os.environ.get("SAFARI_HISTORY_AUDIENCE", ""),
            help="ID token audience; must equal the backend's APP_BASE_URL "
            "(default: the origin of --api-url)",
        )
        target.add_argument("--quiet", action="store_true", help="only report failures")

    export = subparsers.add_parser(
        "export",
        help="export a day, or catch up since the last export",
        epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export.add_argument(
        "day",
        nargs="?",
        type=_valid_day,
        metavar="YYYY-MM-DD",
        help="a specific day to export (default: catch up through yesterday)",
    )
    export.add_argument(
        "--database",
        type=Path,
        default=safari_db.DEFAULT_DATABASE,
        help="Safari history database (default: ~/Library/Safari/History.db)",
    )
    export.add_argument(
        "--max-catchup-days",
        type=_positive_days,
        default=DEFAULT_MAX_CATCHUP_DAYS,
        help=f"most days to export in one run (default: {DEFAULT_MAX_CATCHUP_DAYS})",
    )
    export.add_argument(
        "--no-state",
        action="store_true",
        help="do not advance the catch-up high-water mark",
    )
    export.add_argument(
        "--no-upload", action="store_true", help="write CSVs but do not post them"
    )
    add_common(export)

    upload = subparsers.add_parser(
        "upload",
        help="post any exported day the API has not acknowledged",
        epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    upload.add_argument(
        "days",
        nargs="*",
        type=_valid_day,
        metavar="YYYY-MM-DD",
        help="specific days to (re-)upload (default: everything pending)",
    )
    upload.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be uploaded without sending anything",
    )
    add_common(upload)

    status = subparsers.add_parser(
        "status",
        help="show configuration, permissions, and pending work",
        epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    status.add_argument(
        "--database",
        type=Path,
        default=safari_db.DEFAULT_DATABASE,
        help="Safari history database (default: ~/Library/Safari/History.db)",
    )
    add_common(status)

    return parser


def _normalise(argv: list[str]) -> list[str]:
    """Let the bare form `export-safari-history 2026-07-29` mean `export 2026-07-29`.

    argparse cannot express "a positional that is not one of the subcommand names", so
    the default subcommand is inserted here instead.
    """
    if not argv:
        return ["export"]
    if argv[0] in SUBCOMMANDS or argv[0] in ("-h", "--help"):
        return argv
    return ["export", *argv]


def _resolve_upload_settings(args: argparse.Namespace) -> tuple[str, str, Path]:
    """The three things an upload needs, or a clear complaint about which is missing."""
    if not args.api_url:
        raise ConfigurationError(
            "no API URL: pass --api-url or set SAFARI_HISTORY_API_URL, e.g.\n"
            "  https://agents.example.com/api/browser-history\n"
            "\n"
            "Use `export --no-upload` to export CSVs without posting them."
        )
    if args.service_account_file is None:
        raise ConfigurationError(
            "no service account key: pass --service-account-file or set\n"
            "GOOGLE_APPLICATION_CREDENTIALS to a service account JSON key."
        )
    audience = args.audience or default_audience(args.api_url)
    return args.api_url, audience, args.service_account_file


def _upload_days(
    days: list[date], args: argparse.Namespace, state: State, *, force: bool
) -> int:
    """Upload the given days. Returns the number that failed."""
    available = csv_export.exported_days(args.export_dir)

    failures = 0
    pending: list[tuple[date, Path, str]] = []
    for day in days:
        path = available.get(day)
        if path is None:
            # Counted and carried on rather than returned: naming four days to repair
            # and having the first typo abandon the other three would be its own bug.
            _log_error(f"{day}: no CSV in {args.export_dir} — export it first")
            failures += 1
            continue
        current = csv_export.digest(path)
        if force or state.needs_upload(day, current):
            pending.append((day, path, current))
        elif not args.quiet:
            _log(f"{day}: already uploaded, unchanged since")

    if not pending:
        return failures

    if getattr(args, "dry_run", False):
        for day, path, _ in pending:
            _log(
                f"{day}: would upload {len(csv_export.read_csv(path))} visits from {path}"
            )
        return failures

    api_url, audience, key_file = _resolve_upload_settings(args)
    # Minted once for the whole run: the token is valid for an hour, and asking Google
    # for a new one per day would turn a catch-up into a burst of token requests.
    token = mint_id_token(key_file, audience)

    for day, path, current in pending:
        visits = csv_export.read_csv(path)
        try:
            result = upload_visits(visits, api_url=api_url, token=token)
        except SafariHistoryError as exc:
            _log_error(f"{day}: {exc.message}")
            failures += 1
            continue
        # Recorded and flushed per day, so an interruption halfway through a catch-up
        # does not re-send the days that already landed.
        state.record_upload(day, current, len(visits))
        state.save()
        if not args.quiet:
            _log(
                f"{day}: uploaded {result['received']} visits "
                f"({result['stored']} new to the API)"
            )
    return failures


def command_export(args: argparse.Namespace) -> int:
    state = State.load(args.state_file)

    if args.day is not None:
        days = [args.day]
    else:
        days = catch_up_days(
            state.last_exported_date, local_today(), args.max_catchup_days
        )
        if len(days) == args.max_catchup_days and state.last_exported_date is not None:
            _log(
                f"catching up {len(days)} days (the per-run limit) — run again, or pass "
                "--max-catchup-days, to go further back"
            )

    if not days and not args.quiet:
        _log("nothing to export — already up to date")

    exported: list[date] = []

    # Oldest first, and the high-water mark only advances across the unbroken run of
    # successes at the front: a day that fails blocks the mark rather than being skipped
    # past, so tomorrow's run retries it, while the days after it still get exported now.
    contiguous = True
    last_good: date | None = None
    failures = 0

    for day in days:
        try:
            visits = safari_db.read_visits(day, database=args.database)
            destination = args.export_dir / csv_export.file_name(day)
            csv_export.write_csv(visits, destination)
        except SafariHistoryError as exc:
            _log_error(exc.message)
            failures += 1
            contiguous = False
            # A missing database or a revoked grant fails identically for every
            # remaining day; stopping keeps one broken run from writing thirty copies
            # of the same message into the log.
            if exc.exit_code in (3, 4):
                return exc.exit_code
            continue

        if not args.quiet:
            _log(f"exported {day}: {len(visits)} visits -> {destination}")
        exported.append(day)
        if contiguous:
            last_good = day

    # An explicit date never moves the mark: re-exporting last Tuesday is a repair job,
    # and letting it rewrite the high-water mark would make the next scheduled run
    # re-export every day since.
    if last_good is not None and args.day is None and not args.no_state:
        state.last_exported_date = last_good
        state.save()

    if not args.no_upload and exported:
        failures += _upload_days(exported, args, state, force=True)

    return 1 if failures else 0


def command_upload(args: argparse.Namespace) -> int:
    state = State.load(args.state_file)
    days = args.days or sorted(csv_export.exported_days(args.export_dir))
    if not days:
        if not args.quiet:
            _log(f"nothing to upload — no exports in {args.export_dir}")
        return 0
    # An explicitly named day is always re-sent; a sweep only sends what is pending.
    return 1 if _upload_days(days, args, state, force=bool(args.days)) else 0


def command_status(args: argparse.Namespace) -> int:
    interpreter = Path(sys.executable).resolve()
    print(f"interpreter (needs Full Disk Access): {interpreter}")

    # The whole point of the dedicated virtualenv is that this specific interpreter is
    # the only thing holding the grant. If it is a shared one, the grant would extend to
    # every script anyone runs with it, which is worth saying out loud.
    shared_markers = ("/usr/bin/", "/opt/homebrew/", "/usr/local/", "/.pyenv/", "/uv/")
    if any(marker in str(interpreter) for marker in shared_markers):
        print(
            "  warning: that looks like a shared interpreter. Granting it Full Disk\n"
            "  Access would extend that access to every script run with it. Install\n"
            "  into a dedicated virtualenv instead — see the README."
        )

    print(f"database:    {args.database}")
    try:
        safari_db.read_visits(local_today(), database=args.database)
    except SafariHistoryError as exc:
        print(f"  NOT READABLE: {exc.message.splitlines()[0]}")
    else:
        print("  readable")

    print(f"export dir:  {args.export_dir}")
    exports = csv_export.exported_days(args.export_dir)
    print(f"  {len(exports)} exported day(s)")

    state = State.load(args.state_file)
    print(f"state file:  {args.state_file}")
    print(f"  last exported day: {state.last_exported_date or 'never'}")

    pending = [
        day
        for day, path in exports.items()
        if state.needs_upload(day, csv_export.digest(path))
    ]
    print(
        f"  pending upload: {len(pending)}"
        + (f" (oldest {pending[0]})" if pending else "")
    )

    print(f"api url:     {args.api_url or 'not configured'}")
    if args.api_url:
        try:
            print(
                f"  token audience: {args.audience or default_audience(args.api_url)}"
            )
        except SafariHistoryError as exc:
            print(f"  {exc.message}")
    print(f"credentials: {args.service_account_file or 'not configured'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalise(list(sys.argv[1:] if argv is None else argv)))

    handlers = {
        "export": command_export,
        "upload": command_upload,
        "status": command_status,
    }
    try:
        return handlers[args.command](args)
    except SafariHistoryError as exc:
        _log_error(exc.message)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
