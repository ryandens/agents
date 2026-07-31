"""Posting visits to the API as a Google service account.

The backend accepts two credentials: a browser session cookie, and a Google-signed ID
token presented as a bearer token (see backend/auth.py). A launchd job has no browser to
complete a redirect with, so it takes the second path.

The exchange is the JWT-bearer flow. This tool signs a short-lived assertion with the
service account's private key, hands it to Google, and gets back an ID token that Google
signed. Only the second token is sent to the API, which is the point: the API never has
to trust anything this machine signed, it verifies Google's signature against Google's
published certificates.

The `target_audience` baked into that token is what stops it being replayed elsewhere.
The backend verifies the audience equals its own APP_BASE_URL, so a token minted for
this API is useless at any other service the same account can reach.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from safari_history.errors import ConfigurationError, UploadFailed

# Small enough that a day of heavy browsing is a handful of requests, and comfortably
# under the API's own per-request cap.
DEFAULT_BATCH_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3


def default_audience(api_url: str) -> str:
    """The origin of `api_url`, which is what the backend checks the token against.

    Derived from the API URL rather than configured separately because the two have to
    agree, and a mismatch produces a flat 401 with nothing to say why.
    """
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigurationError(
            f"'{api_url}' is not a full URL — expected something like "
            "https://agents.example.com/api/browser-history"
        )
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def mint_id_token(service_account_file: Path, audience: str) -> str:
    """A Google-signed ID token for `audience`, from the service account's key."""
    if not service_account_file.exists():
        raise ConfigurationError(
            f"no service account key at {service_account_file}.\n"
            "\n"
            "Create one in the Google Cloud console (IAM -> Service Accounts -> Keys ->\n"
            "Add key -> JSON), save it somewhere only your user can read, and point\n"
            "--service-account-file or GOOGLE_APPLICATION_CREDENTIALS at it."
        )
    try:
        credentials = service_account.IDTokenCredentials.from_service_account_file(
            str(service_account_file), target_audience=audience
        )
        credentials.refresh(GoogleRequest())
    except (GoogleAuthError, ValueError, OSError) as exc:
        raise UploadFailed(
            f"could not mint an ID token from {service_account_file}: {exc}\n"
            "\n"
            "Check that the file is an unmodified service account JSON key and that the\n"
            "key has not been disabled or deleted in the Google Cloud console."
        ) from exc

    token = credentials.token
    if not token:
        raise UploadFailed(
            f"Google returned no ID token for audience {audience}. Check that the "
            "service account still exists and its key is enabled."
        )
    return token


def _batches(visits: Sequence[dict], size: int) -> Iterator[Sequence[dict]]:
    for start in range(0, len(visits), size):
        yield visits[start : start + size]


def _post_batch(
    session: requests.Session, api_url: str, token: str, batch: Sequence[dict]
) -> dict:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(
                api_url,
                json=list(batch),
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code < 300:
                try:
                    return response.json()
                except ValueError:
                    return {}

            body = response.text[:400]
            # 401 and 403 will fail identically on every retry — the token is wrong, or
            # the account is not on the backend's ALLOWED_SERVICE_ACCOUNTS list. Say so
            # rather than spending two more attempts to reach the same conclusion.
            if response.status_code in (401, 403):
                raise UploadFailed(
                    f"the API rejected this service account ({response.status_code}): {body}\n"
                    "\n"
                    "Check that the account's email is in the backend's\n"
                    "ALLOWED_SERVICE_ACCOUNTS, and that the token audience matches the\n"
                    "backend's APP_BASE_URL exactly (scheme and host, no trailing path)."
                )
            if response.status_code < 500 and response.status_code != 429:
                raise UploadFailed(
                    f"the API refused the batch ({response.status_code}): {body}"
                )
            last_error = f"HTTP {response.status_code}: {body}"

        if attempt < MAX_ATTEMPTS:
            # A plain backoff. This runs once a night against one service; anything
            # cleverer would be more machinery than the problem deserves.
            time.sleep(2**attempt)

    raise UploadFailed(
        f"giving up after {MAX_ATTEMPTS} attempts against {api_url} — {last_error}"
    )


def upload_visits(
    visits: Sequence[dict],
    *,
    api_url: str,
    token: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session: requests.Session | None = None,
) -> dict:
    """Post visits in batches. Returns totals reported by the API."""
    owned_session = session is None
    session = session or requests.Session()

    received = 0
    stored = 0
    try:
        # An empty day still posts once, so a quiet day is recorded as uploaded rather
        # than retried every night forever.
        for batch in _batches(visits, batch_size) if visits else [[]]:
            result = _post_batch(session, api_url, token, batch)
            received += int(result.get("received", len(batch)))
            stored += int(result.get("stored", 0))
    finally:
        if owned_session:
            session.close()

    return {"received": received, "stored": stored}
