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

import re
import sys
import time
import urllib.error
import urllib.request

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
    """/health returns ok, so the ALB target group stays healthy"""
    status, _, body = fetch(f"{base_url}/health")
    assert status == 200, f"expected 200, got {status}"
    assert b'"ok"' in body, f"expected status ok, got {body[:200]!r}"


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

    if failures:
        print(f"\n{len(failures)} of {len(CHECKS)} checks failed")
        return 1
    print(f"\nall {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
