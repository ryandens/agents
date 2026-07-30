from urllib.parse import parse_qs, urlparse

import pytest
import requests
from fastapi.testclient import TestClient

import auth
from main import app

ALLOWED = "cook@example.com"


@pytest.fixture(autouse=True)
def oauth_config(monkeypatch):
    """Give the module the credentials and allowlist it reads at request time."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ALLOWED_EMAILS", f" {ALLOWED.upper()} , other@example.com")


@pytest.fixture
def client():
    # follow_redirects=False so the 302s the flow is built on can be asserted directly.
    return TestClient(app, follow_redirects=False)


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


def test_callback_rejects_mismatched_state(client, monkeypatch):
    _, nonce = start_login(client)

    resp = complete_callback(
        client, monkeypatch, state="forged-state", id_claims=claims(nonce=nonce)
    )

    assert resp.headers["location"] == "/?error=state_mismatch"


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


def test_google_reported_error_short_circuits(client):
    resp = client.get("/api/auth/callback?error=access_denied&state=x")

    assert resp.headers["location"] == "/?error=access_denied"


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
