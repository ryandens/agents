import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from fastapi.testclient import TestClient

import auth
import main
from main import app

ALLOWED = "cook@example.com"


def _session_of(client) -> dict:
    """Decode the session cookie, which is signed but not encrypted."""
    payload = client.cookies["agents_session"].strip('"').split(".")[0]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@pytest.fixture(autouse=True)
def oauth_config(monkeypatch):
    """Give the module the credentials and allowlist it reads at request time."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ALLOWED_EMAILS", f" {ALLOWED.upper()} , other@example.com")


class EmptyPantry:
    """Stands in for the store on the route these tests use as a protected endpoint.

    /api/pantry is incidental here — what is under test is who gets past
    `authenticated` — so the route is handed an empty pantry rather than a database,
    which keeps this whole file free of Postgres.
    """

    def list_items(self, location=None):
        return []


@pytest.fixture
def client():
    app.dependency_overrides[main.store] = EmptyPantry
    # follow_redirects=False so the 302s the flow is built on can be asserted directly.
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def token_response(status=200, id_token_value="fake-id-token"):
    class Response:
        status_code = status

        def json(self):
            return {"id_token": id_token_value} if id_token_value else {}

    return Response()


def claims(**overrides):
    base = {
        "iss": "https://accounts.google.com",
        "sub": "google-user-1",
        "email": ALLOWED,
        "email_verified": True,
        "name": "Cook",
        "picture": "",
    }
    base.update(overrides)
    return base


def start_login(client):
    """Run /login and return the nonce Google would echo back in the ID token."""
    resp = client.get("/api/auth/login")
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    return query["state"][0], query["nonce"][0]


def complete_callback(client, monkeypatch, *, state, id_claims, exchange=None):
    monkeypatch.setattr(requests, "post", lambda *a, **k: exchange or token_response())
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", lambda *a, **k: id_claims)
    return client.get(f"/api/auth/callback?code=abc&state={state}")


def test_login_redirects_to_google_with_pkce_and_state(client):
    resp = client.get("/api/auth/login")

    assert resp.status_code == 302
    url = urlparse(resp.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == auth.GOOGLE_AUTH_ENDPOINT

    query = parse_qs(url.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    # An unpadded base64url S256 challenge of a 32-byte digest is always 43 chars.
    assert len(query["code_challenge"][0]) == 43
    assert "=" not in query["code_challenge"][0]
    assert query["state"] and query["nonce"]


def test_login_without_credentials_errors(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")

    assert client.get("/api/auth/login").status_code == 500


def test_callback_signs_in_allowlisted_user(client, monkeypatch):
    state, nonce = start_login(client)

    resp = complete_callback(
        client, monkeypatch, state=state, id_claims=claims(nonce=nonce)
    )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == ALLOWED


def test_callback_rejects_email_off_the_allowlist(client, monkeypatch):
    state, nonce = start_login(client)

    resp = complete_callback(
        client,
        monkeypatch,
        state=state,
        id_claims=claims(email="stranger@example.com", nonce=nonce),
    )

    assert resp.headers["location"] == "/?error=not_authorized"
    assert client.get("/api/auth/me").status_code == 401


def test_callback_rejects_unverified_email(client, monkeypatch):
    state, nonce = start_login(client)

    resp = complete_callback(
        client,
        monkeypatch,
        state=state,
        id_claims=claims(email_verified=False, nonce=nonce),
    )

    assert resp.headers["location"] == "/?error=email_unverified"


def test_callback_ignores_a_state_it_never_issued(client, monkeypatch):
    _, nonce = start_login(client)

    resp = complete_callback(
        client, monkeypatch, state="forged-state", id_claims=claims(nonce=nonce)
    )

    # Silently back to the app: an unsolicited callback reveals nothing and, crucially,
    # leaves the session untouched.
    assert resp.headers["location"] == "/"


def test_callback_rejects_replayed_token_with_wrong_nonce(client, monkeypatch):
    state, _ = start_login(client)

    resp = complete_callback(
        client, monkeypatch, state=state, id_claims=claims(nonce="some-other-nonce")
    )

    assert resp.headers["location"] == "/?error=nonce_mismatch"


def test_callback_rejects_untrusted_issuer(client, monkeypatch):
    state, nonce = start_login(client)

    resp = complete_callback(
        client,
        monkeypatch,
        state=state,
        id_claims=claims(iss="https://evil.example.com", nonce=nonce),
    )

    assert resp.headers["location"] == "/?error=invalid_issuer"


def test_callback_surfaces_failed_code_exchange(client, monkeypatch):
    state, nonce = start_login(client)

    resp = complete_callback(
        client,
        monkeypatch,
        state=state,
        id_claims=claims(nonce=nonce),
        exchange=token_response(status=400),
    )

    assert resp.headers["location"] == "/?error=token_exchange_failed"


def test_callback_passes_secret_and_verifier_to_google(client, monkeypatch):
    state, nonce = start_login(client)
    sent = {}

    def capture(url, data=None, timeout=None):
        sent["url"] = url
        sent["data"] = data
        return token_response()

    monkeypatch.setattr(requests, "post", capture)
    monkeypatch.setattr(
        auth.id_token, "verify_oauth2_token", lambda *a, **k: claims(nonce=nonce)
    )
    client.get(f"/api/auth/callback?code=abc&state={state}")

    assert sent["url"] == auth.GOOGLE_TOKEN_ENDPOINT
    assert sent["data"]["client_secret"] == "test-client-secret"
    assert sent["data"]["grant_type"] == "authorization_code"
    assert sent["data"]["code_verifier"]


def test_google_reported_error_surfaces_for_a_flow_we_started(client):
    state, _ = start_login(client)

    resp = client.get(f"/api/auth/callback?error=access_denied&state={state}")

    assert resp.headers["location"] == "/?error=access_denied"


def test_unsolicited_error_callback_cannot_log_a_user_out(client, monkeypatch):
    """Regression: ?error= used to clear the session before state was checked.

    SameSite=Lax sends the session cookie on a top-level GET, so linking a signed-in
    user to this URL was a working forced-logout.
    """
    state, nonce = start_login(client)
    complete_callback(client, monkeypatch, state=state, id_claims=claims(nonce=nonce))
    assert client.get("/api/auth/me").status_code == 200

    resp = client.get("/api/auth/callback?error=access_denied&state=attacker-supplied")

    assert resp.headers["location"] == "/"
    assert client.get("/api/auth/me").status_code == 200


def test_the_earlier_of_two_concurrent_sign_ins_still_completes(client, monkeypatch):
    """Regression: a second tab used to overwrite the first tab's state/nonce/verifier,
    which broke both flows. Finishing the *earlier* one is the case that used to fail."""
    first_state, first_nonce = start_login(client)
    second_state, _ = start_login(client)
    assert first_state != second_state

    resp = complete_callback(
        client, monkeypatch, state=first_state, id_claims=claims(nonce=first_nonce)
    )

    assert resp.headers["location"] == "/"
    assert client.get("/api/auth/me").status_code == 200


def test_the_later_of_two_concurrent_sign_ins_also_completes(client, monkeypatch):
    start_login(client)
    second_state, second_nonce = start_login(client)

    resp = complete_callback(
        client, monkeypatch, state=second_state, id_claims=claims(nonce=second_nonce)
    )

    assert resp.headers["location"] == "/"
    assert client.get("/api/auth/me").status_code == 200


def test_a_pending_flow_is_single_use(client, monkeypatch):
    state, nonce = start_login(client)
    complete_callback(client, monkeypatch, state=state, id_claims=claims(nonce=nonce))
    client.post("/api/auth/logout")

    replay = complete_callback(
        client, monkeypatch, state=state, id_claims=claims(nonce=nonce)
    )

    assert replay.headers["location"] == "/"
    assert client.get("/api/auth/me").status_code == 401


def test_pending_flows_are_bounded(client):
    for _ in range(auth.PENDING_MAX + 3):
        start_login(client)

    # Reachable because the cookie is signed, not encrypted — and the point is that an
    # unbounded dict here would eventually blow the browser's ~4KB cookie limit.
    session = _session_of(client)
    assert len(session["oidc_pending"]) == auth.PENDING_MAX


def test_expired_pending_flows_are_dropped(client, monkeypatch):
    state, nonce = start_login(client)

    # auth.time is the stdlib module, so capture the real function before patching it —
    # calling time.time() inside the replacement would recurse into itself.
    real_time = time.time
    monkeypatch.setattr(
        auth.time, "time", lambda: real_time() + auth.PENDING_TTL_SECONDS + 1
    )
    # Pruning happens on the next /login, so the stale entry is gone by the callback.
    start_login(client)
    resp = complete_callback(
        client, monkeypatch, state=state, id_claims=claims(nonce=nonce)
    )

    assert resp.headers["location"] == "/"


def test_logout_clears_the_session(client, monkeypatch):
    state, nonce = start_login(client)
    complete_callback(client, monkeypatch, state=state, id_claims=claims(nonce=nonce))
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")

    assert client.get("/api/auth/me").status_code == 401


def test_api_rejects_a_session_whose_email_left_the_allowlist(client, monkeypatch):
    state, nonce = start_login(client)
    complete_callback(client, monkeypatch, state=state, id_claims=claims(nonce=nonce))

    # The cookie is still valid and unexpired; only the allowlist changed.
    monkeypatch.setenv("ALLOWED_EMAILS", "someone-else@example.com")

    assert client.get("/api/pantry").status_code == 403


def test_api_requires_a_session(client):
    assert client.get("/api/pantry").status_code == 401


# ── Service account bearer tokens ─────────────────────────────────────────────

SERVICE_ACCOUNT = "batch@example-project.iam.gserviceaccount.com"
APP_ORIGIN = "https://agents.example.ts.net"


@pytest.fixture
def service_account_config(monkeypatch):
    """Turn on bearer auth and pin the origin its audience check is built from."""
    monkeypatch.setenv("APP_BASE_URL", APP_ORIGIN)
    monkeypatch.setenv("ALLOWED_SERVICE_ACCOUNTS", f" {SERVICE_ACCOUNT.upper()} ,")


def sa_claims(**overrides):
    base = {
        "iss": "https://accounts.google.com",
        "sub": "service-account-1",
        "email": SERVICE_ACCOUNT,
        "email_verified": True,
        "aud": APP_ORIGIN,
    }
    base.update(overrides)
    return base


@pytest.fixture
def verified(monkeypatch):
    """Stand in for Google's verification, recording the audience it was asked for."""
    calls = []

    def install(result):
        def fake(token, request, audience=None, *a, **k):
            calls.append({"token": token, "audience": audience})
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(auth.id_token, "verify_oauth2_token", fake)
        return calls

    return install


def bearer(client, token="sa-token"):
    return client.get("/api/pantry", headers={"Authorization": f"Bearer {token}"})


def test_bearer_token_from_an_allowed_service_account_is_accepted(
    client, service_account_config, verified
):
    verified(sa_claims())

    assert bearer(client).status_code == 200


def test_bearer_token_is_verified_against_the_app_origin(
    client, service_account_config, verified
):
    calls = verified(sa_claims())

    bearer(client, token="the-token")

    # The audience is what stops a token minted for another service being replayed here,
    # so assert the exact value rather than just that verification happened.
    assert calls == [{"token": "the-token", "audience": APP_ORIGIN}]


def test_bearer_token_is_ignored_when_no_service_accounts_are_configured(
    client, monkeypatch, verified
):
    monkeypatch.setenv("APP_BASE_URL", APP_ORIGIN)
    monkeypatch.delenv("ALLOWED_SERVICE_ACCOUNTS", raising=False)
    calls = verified(sa_claims())

    assert bearer(client).status_code == 401
    # Not merely rejected — never verified at all, so the default config spends nothing
    # and reveals nothing about which tokens are well-formed.
    assert calls == []


def test_bearer_token_from_an_unlisted_service_account_is_rejected(
    client, service_account_config, verified
):
    verified(sa_claims(email="other@example-project.iam.gserviceaccount.com"))

    assert bearer(client).status_code == 401


def test_allowed_emails_does_not_grant_bearer_access(
    client, service_account_config, verified
):
    """The two allowlists stay separate: a human sign-in address is not a machine key."""
    verified(sa_claims(email=ALLOWED))

    assert bearer(client).status_code == 401


@pytest.mark.parametrize(
    "result",
    [
        ValueError("bad token"),
        auth.GoogleAuthError("cert fetch failed"),
    ],
    ids=["invalid", "auth-error"],
)
def test_bearer_token_that_fails_verification_is_rejected(
    client, service_account_config, verified, result
):
    verified(result)

    assert bearer(client).status_code == 401


def test_bearer_token_with_an_unverified_email_is_rejected(
    client, service_account_config, verified
):
    verified(sa_claims(email_verified=False))

    assert bearer(client).status_code == 401


def test_bearer_token_from_a_foreign_issuer_is_rejected(
    client, service_account_config, verified
):
    verified(sa_claims(iss="https://evil.example.com"))

    assert bearer(client).status_code == 401


@pytest.mark.parametrize(
    "header",
    ["", "Basic abc123", "Bearer", "Bearer   "],
    ids=["empty", "wrong-scheme", "no-token", "blank-token"],
)
def test_non_bearer_authorization_headers_are_rejected(
    client, service_account_config, verified, header
):
    calls = verified(sa_claims())

    resp = client.get(
        "/api/pantry", headers={"Authorization": header} if header else {}
    )

    assert resp.status_code == 401
    assert calls == []


def test_a_session_still_wins_when_a_bearer_token_is_also_present(
    client, monkeypatch, service_account_config, verified
):
    """A signed-in browser keeps its own identity even if a header rides along."""
    state, nonce = start_login(client)
    complete_callback(client, monkeypatch, state=state, id_claims=claims(nonce=nonce))
    calls = verified(sa_claims())

    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer sa-token"})

    assert resp.status_code == 200
    assert resp.json()["email"] == ALLOWED
    assert calls == []
