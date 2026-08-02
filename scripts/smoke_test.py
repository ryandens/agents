#!/usr/bin/env python3
"""Smoke-test a running agents container.

The point of these checks is the single-origin layout: one process has to serve the
React export at / and the JSON API under /api, without either shadowing the other.
That is exactly the seam a unit test cannot see, because it only exists once the
frontend has been built into the image.

Deliberately stdlib-only so CI can run it without installing anything.

    just smoke                                    # build, run, and check
    python3 scripts/smoke_test.py http://host:8080
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from datetime import time as clock
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
READY_TIMEOUT_SECONDS = 90
REQUEST_TIMEOUT_SECONDS = 10

CHUNK_PATTERN = re.compile(r'"(/_next/static/[^"]+\.js)"')


class SkipCheck(Exception):
    """Raised by a check that cannot run in this environment."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses instead of transparently following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_following = urllib.request.build_opener()
_not_following = urllib.request.build_opener(_NoRedirect)


def fetch(url, method="GET", body=None, follow_redirects=True):
    """Return (status, headers, body) — HTTP errors are results here, not exceptions.

    headers stays an HTTPMessage rather than a dict so lookups are case-insensitive;
    uvicorn sends header names lowercased.
    """
    request = urllib.request.Request(url, method=method, data=body)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    opener = _following if follow_redirects else _not_following
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def wait_until_ready(base_url):
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    last_error = "no attempt made"
    while time.monotonic() < deadline:
        try:
            status, _, body = fetch(f"{base_url}/health")
            if status == 200:
                return
            last_error = f"HTTP {status}: {body[:200]!r}"
        except OSError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise SystemExit(
        f"container never became ready at {base_url} after "
        f"{READY_TIMEOUT_SECONDS}s — last error: {last_error}"
    )


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def health_responds(base_url):
    """/health returns ok, which is what user_data waits on before finishing boot"""
    status, _, body = fetch(f"{base_url}/health")
    assert status == 200, f"expected 200, got {status}"
    payload = json.loads(body)
    assert payload.get("status") == "ok", f"expected status ok, got {payload!r}"


# The seam the unit tests cannot see: whether the image can really open a connection —
# driver present, DATABASE_URL honoured — rather than whether the SQL is right. /health
# is also what user_data.sh and `just restart` wait on, so a container answering 200 with
# no database behind it would let a broken deploy through both gates.
@check
def health_reports_a_reachable_database(base_url):
    """/health reports the database it reached, not just that the process is up"""
    _, _, body = fetch(f"{base_url}/health")
    payload = json.loads(body)
    assert payload.get("database") == "ok", (
        f"health did not report a reachable database: {payload!r}"
    )


@check
def root_serves_the_react_app(base_url):
    """/ returns the built frontend rather than a JSON 404"""
    status, headers, body = fetch(f"{base_url}/")
    assert status == 200, f"expected 200, got {status}"
    content_type = headers.get("Content-Type", "")
    assert "text/html" in content_type, f"expected html, got {content_type!r}"
    assert b"<title>Kitchen Agent</title>" in body, "app title missing from /"
    assert b"/_next/static/" in body, "no Next.js assets referenced by /"


@check
def hashed_assets_are_served(base_url):
    """the _next/static bundles the page references actually resolve"""
    _, _, index = fetch(f"{base_url}/")
    chunks = CHUNK_PATTERN.findall(index.decode("utf-8", "replace"))
    assert chunks, "index.html referenced no /_next/static/*.js chunks"
    path = chunks[0]
    status, headers, _ = fetch(f"{base_url}{path}")
    assert status == 200, f"expected 200 for {path}, got {status}"
    content_type = headers.get("Content-Type", "")
    assert "javascript" in content_type, f"expected javascript, got {content_type!r}"


@check
def nested_route_is_served(base_url):
    """/pantry/ resolves to the exported pantry/index.html"""
    status, headers, body = fetch(f"{base_url}/pantry/")
    assert status == 200, f"expected 200, got {status}"
    assert "text/html" in headers.get("Content-Type", ""), "expected html"
    assert b"<title>Kitchen Agent</title>" in body, "app title missing from /pantry/"


@check
def nested_route_redirects_to_trailing_slash(base_url):
    """/pantry redirects to /pantry/, matching the trailingSlash export"""
    status, headers, _ = fetch(f"{base_url}/pantry", follow_redirects=False)
    assert status in (301, 307, 308), f"expected a redirect, got {status}"
    location = headers.get("Location", "")
    assert location.endswith("/pantry/"), f"expected /pantry/, got {location!r}"


@check
def api_is_not_shadowed_by_static_files(base_url):
    """/api routes still reach FastAPI and enforce auth, despite the mount at /"""
    for method, path, body in (
        ("GET", "/api/pantry", None),
        ("POST", "/api/chat", b'{"messages":[]}'),
        ("PATCH", "/api/pantry/8d1c1b1e-0000-4000-8000-000000000000", b"{}"),
        # The exporter's endpoint. Worth a check of its own: it is the one route
        # reached by a machine rather than a browser, so nobody would notice the
        # static mount swallowing it by clicking around.
        ("POST", "/api/browser-history", b"[]"),
    ):
        status, headers, payload = fetch(
            f"{base_url}{path}", method=method, body=body, follow_redirects=False
        )
        assert status == 401, f"{method} {path}: expected 401, got {status}"
        content_type = headers.get("Content-Type", "")
        assert "application/json" in content_type, (
            f"{method} {path}: expected a JSON error, got {content_type!r} — "
            "the static mount may be swallowing API routes"
        )
        assert b"Unauthorized" in payload or b"detail" in payload, (
            f"{method} {path}: unexpected body {payload[:200]!r}"
        )


@check
def unknown_paths_return_404(base_url):
    """an unrouted path falls through to the export's 404 page"""
    status, _, _ = fetch(f"{base_url}/definitely-not-a-real-page")
    assert status == 404, f"expected 404, got {status}"


@check
def login_redirects_to_google(base_url):
    """/api/auth/login hands off to Google's authorization endpoint"""
    status, headers, _ = fetch(f"{base_url}/api/auth/login", follow_redirects=False)
    assert status == 302, f"expected a 302 to Google, got {status}"

    location = headers.get("Location", "")
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth"), (
        f"expected Google's authorization endpoint, got {location!r}"
    )
    # The parts that make this the code flow rather than the old implicit ID token one.
    for param in ("response_type=code", "code_challenge_method=S256", "state="):
        assert param in location, f"missing {param!r} in {location!r}"

    # Starlette lowercases the attribute names, so compare case-insensitively.
    set_cookie = headers.get("Set-Cookie", "").lower()
    assert "agents_session" in set_cookie, (
        f"login did not set a session cookie to carry state/nonce: {set_cookie!r}"
    )
    assert "httponly" in set_cookie, f"session cookie is not HttpOnly: {set_cookie!r}"
    assert "samesite=lax" in set_cookie, (
        f"session cookie needs SameSite=Lax to survive the redirect back from Google: "
        f"{set_cookie!r}"
    )


@check
def auth_me_is_unauthorized_without_a_session(base_url):
    """/api/auth/me refuses an anonymous caller"""
    status, _, _ = fetch(f"{base_url}/api/auth/me", follow_redirects=False)
    assert status == 401, f"expected 401, got {status}"


# --- The Safari exporter against the running image ---
#
# The seam these cover is the one between cli/ and backend/: unit tests on either side
# both pass while the exporter posts a shape the API would reject. Everything here runs
# the *packaged* CLI as a subprocess against a stub History.db, so it also covers the
# entry point, the SQLite read and the CSV round trip as they are actually installed.
#
# What they deliberately do not cover is an authenticated upload. A bearer token has to
# be signed by Google — auth.py verifies against Google's certs — so it cannot be minted
# offline, and the alternative would be a test-only bypass in the shipped image. The
# checks below therefore stop at the last point reachable without credentials: the
# payload the CLI would send, validated against the API's own published schema, and then
# refused by the real endpoint.

REPO_ROOT = Path(__file__).resolve().parent.parent

# Safari records visit_time as a CFAbsoluteTime — seconds since 2001-01-01 UTC. Derived
# from the definition rather than written as 978307200, the same way safari_db.py does,
# so this stub cannot silently agree with a wrong constant on the other side. If the two
# ever disagreed the export would come back empty and the first check would fail.
SAFARI_EPOCH_OFFSET = datetime(2001, 1, 1, tzinfo=UTC).timestamp()

# Yesterday rather than a fixed date: `export <day>` refuses today, and a hardcoded date
# would drift out of whatever range a future version considers exportable.
STUB_DAY = datetime.now().astimezone().date() - timedelta(days=1)
STUB_VISITS = [
    (clock(9, 14), "https://example.com/page?a=1&b=2", 'A "quoted", comma title'),
    (clock(21, 40), "https://news.example.com/", "News"),
]

_workspace = None


def cli_workspace():
    """A stub Safari database plus scratch dirs, built once and shared by the checks."""
    global _workspace
    if _workspace is not None:
        return _workspace

    if shutil.which("uv") is None:
        raise SkipCheck("uv is not installed")
    if not (REPO_ROOT / "cli" / "pyproject.toml").is_file():
        raise SkipCheck("cli/ is not present")

    root = Path(tempfile.mkdtemp(prefix="agents-cli-smoke-"))
    database = root / "History.db"
    # Only the columns the exporter reads. Safari's real tables have many more.
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE history_items (
                id INTEGER PRIMARY KEY, url TEXT NOT NULL, visit_count INTEGER
            );
            CREATE TABLE history_visits (
                id INTEGER PRIMARY KEY, history_item INTEGER NOT NULL,
                visit_time REAL NOT NULL, title TEXT
            );
        """)
        for index, (at, url, title) in enumerate(STUB_VISITS, start=1):
            moment = datetime.combine(STUB_DAY, at).astimezone()
            connection.execute(
                "INSERT INTO history_items (id, url, visit_count) VALUES (?, ?, 1)",
                (index, url),
            )
            connection.execute(
                "INSERT INTO history_visits (id, history_item, visit_time, title) "
                "VALUES (?, ?, ?, ?)",
                (index, index, moment.timestamp() - SAFARI_EPOCH_OFFSET, title),
            )

    _workspace = {
        "root": root,
        "database": database,
        "exports": root / "exports",
        "state": root / "state.json",
    }
    return _workspace


def run_cli(*args, expect_success=True):
    """Run the packaged CLI from cli/, returning its completed process."""
    result = subprocess.run(
        ["uv", "run", "--project", "cli", "export-safari-history", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"`export-safari-history {' '.join(args)}` exited {result.returncode}\n"
            f"          stdout: {result.stdout.strip()}\n"
            f"          stderr: {result.stderr.strip()}"
        )
    return result


def exported_csv():
    space = cli_workspace()
    return space["exports"] / f"Safari History - {STUB_DAY.isoformat()}.csv"


@check
def cli_exports_a_stub_database(base_url):
    """the packaged CLI turns a stub Safari database into the documented CSV"""
    space = cli_workspace()
    run_cli(
        "export",
        STUB_DAY.isoformat(),
        "--database",
        str(space["database"]),
        "--export-dir",
        str(space["exports"]),
        "--state-file",
        str(space["state"]),
        "--no-upload",
    )

    written = exported_csv()
    assert written.is_file(), f"no CSV at {written}"
    lines = written.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "visited_at,title,url", f"unexpected header {lines[0]!r}"
    assert len(lines) == 1 + len(STUB_VISITS), (
        f"expected {len(STUB_VISITS)} rows, got {len(lines) - 1}: {lines[1:]}"
    )
    for _, url, _ in STUB_VISITS:
        assert url in written.read_text(encoding="utf-8"), f"{url} missing from export"


@check
def cli_reads_its_own_export_back(base_url):
    """the CLI parses the CSV it wrote into the visits it would upload"""
    space = cli_workspace()
    result = run_cli(
        "upload",
        STUB_DAY.isoformat(),
        "--export-dir",
        str(space["exports"]),
        "--state-file",
        str(space["state"]),
        "--dry-run",
    )
    expected = f"would upload {len(STUB_VISITS)} visits"
    assert expected in result.stdout, (
        f"expected {expected!r} in dry-run output, got: {result.stdout.strip()}"
    )


# Runs the uploader's own reader, so what is validated below is the payload the CLI
# would really post rather than this file's idea of it.
_PAYLOAD_PROGRAM = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from safari_history import csv_export\n"
    "print(json.dumps(csv_export.read_csv(Path(sys.argv[1]))))\n"
)


def cli_payload():
    """The exact list of dicts the uploader would post, built by the CLI's own code."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "cli",
            "python",
            "-c",
            _PAYLOAD_PROGRAM,
            str(exported_csv()),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (
        f"could not build the payload: {result.stderr.strip()}"
    )
    return json.loads(result.stdout)


@check
def cli_payload_matches_the_api_schema(base_url):
    """the visits the CLI would post satisfy the running image's own SiteVisit schema"""
    status, _, body = fetch(f"{base_url}/openapi.json")
    assert status == 200, f"expected 200 from /openapi.json, got {status}"
    schema = json.loads(body)["components"]["schemas"]["SiteVisit"]

    properties = schema["properties"]
    required = set(schema["required"])
    visits = cli_payload()
    assert visits, "the CLI produced no visits to post"

    for visit in visits:
        missing = required - visit.keys()
        assert not missing, f"visit is missing {sorted(missing)}: {visit}"
        # additionalProperties is false on SiteVisit, so an extra key is a 422 in
        # production — exactly the mismatch these two test suites cannot see alone.
        extra = visit.keys() - properties.keys()
        assert not extra, (
            f"visit carries fields the API forbids {sorted(extra)}: {visit}"
        )
        for field, value in visit.items():
            spec = properties[field]
            assert isinstance(value, str), f"{field} should be a string, got {value!r}"
            if "maxLength" in spec:
                assert len(value) <= spec["maxLength"], f"{field} is over maxLength"
            if "minLength" in spec:
                assert len(value) >= spec["minLength"], f"{field} is under minLength"

    # The offset is what makes a late-night visit land on the right local day, and the
    # API rejects a naive timestamp outright.
    for visit in visits:
        stamp = visit["timestamp"]
        assert datetime.fromisoformat(stamp).utcoffset() is not None, (
            f"timestamp {stamp!r} carries no UTC offset"
        )


@check
def the_api_refuses_the_cli_payload_without_credentials(base_url):
    """POST /api/browser-history rejects the CLI's real payload when unauthenticated"""
    body = json.dumps(cli_payload()).encode("utf-8")
    status, headers, payload = fetch(
        f"{base_url}/api/browser-history",
        method="POST",
        body=body,
        follow_redirects=False,
    )
    assert status == 401, f"expected 401, got {status}: {payload[:200]!r}"
    assert "application/json" in headers.get("Content-Type", ""), (
        "expected a JSON error — the static mount may be swallowing the route"
    )


def main(argv):
    base_url = (argv[1] if len(argv) > 1 else DEFAULT_BASE_URL).rstrip("/")
    print(f"smoke-testing {base_url}")
    wait_until_ready(base_url)

    failures = []
    for fn in CHECKS:
        label = fn.__doc__ or fn.__name__
        try:
            fn(base_url)
        except SkipCheck as exc:
            print(f"  skip  {label} ({exc})")
        except (AssertionError, OSError) as exc:
            print(f"  FAIL  {label}\n          {exc}")
            failures.append((fn.__name__, exc))
        else:
            print(f"  ok    {label}")

    if _workspace is not None:
        shutil.rmtree(_workspace["root"], ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} of {len(CHECKS)} checks failed")
        return 1
    print(f"\nall {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
