"""Google OIDC sign-in: authorization code flow with PKCE, plus a session cookie.

The browser never sees a Google token. It gets redirected to Google, comes back with a
one-time code, and the backend exchanges that code for an ID token over a direct TLS
connection to Google using the client secret. The ID token is verified and then thrown
away — all that survives is a signed, HttpOnly session cookie holding the user's claims.

Access is gated by ALLOWED_EMAILS, not by anything configured in the Google Cloud
console. Google's Testing-mode test-user list does not apply to apps that request only
openid/email/profile (see https://support.google.com/cloud/answer/15549945), so an
External OAuth client lets any Google account reach the callback. The allowlist is what
stops them, which is why an empty ALLOWED_EMAILS denies everyone rather than allowing
everyone.
"""

import base64
import os
import secrets
from hashlib import sha256
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Google's endpoints, from https://accounts.google.com/.well-known/openid-configuration.
# Hardcoded rather than discovered at runtime: they have been stable for years, and a
# discovery fetch would add a startup failure mode for no practical benefit. The JWKS
# endpoint is not listed because google-auth fetches Google's signing certs itself.
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

# Authentication only. Widening this past these three would opt the app into Google's
# test-user and verification requirements, which is a deliberate reason to keep it here.
SCOPES = "openid email profile"


def client_id() -> str:
    """The Google OAuth client ID. Read per-call rather than at import so load_dotenv() can run first."""
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def client_secret() -> str:
    """The Google OAuth client secret. Read per-call rather than at import so load_dotenv() can run first."""
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


# Where Google sends the user back. Must match a registered redirect URI on the OAuth
# client exactly, including scheme and port.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000").rstrip("/")
REDIRECT_URI = f"{APP_BASE_URL}/api/auth/callback"

# Sessions ride an https-only cookie in production. Derived from APP_BASE_URL so there
# is one switch to get wrong instead of two — `http://localhost:3000` in dev turns the
# Secure flag off, which the browser requires for a cookie to stick over plain http.
COOKIE_SECURE = APP_BASE_URL.startswith("https://")

_auth_request = google_requests.Request()


def allowed_emails() -> frozenset[str]:
    """The set of addresses permitted to sign in, lowercased.

    Read per-call rather than at import so tests can set it with monkeypatch.
    """
    raw = os.environ.get("ALLOWED_EMAILS", "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


router = APIRouter(prefix="/api/auth")


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    """Kick off the code flow: stash PKCE/CSRF material, then bounce to Google."""
    if not client_id() or not client_secret():
        raise HTTPException(
            status_code=500,
            detail="Sign-in is not configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
        )

    # token_urlsafe(32) is 256 bits of entropy, well past the 128-bit floor RFC 7636
    # sets for a PKCE verifier and RFC 6749 for state.
    verifier = secrets.token_urlsafe(32)
    # S256: base64url(sha256(verifier)), unpadded per RFC 7636 §4.2.
    challenge = (
        base64.urlsafe_b64encode(sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # The session cookie is signed, so the browser can read these but cannot forge them.
    # That is the property state and nonce need; the PKCE verifier is the client's own
    # secret by design, so holding it client-side is what RFC 7636 intends.
    request.session.update(
        {"oidc_state": state, "oidc_nonce": nonce, "oidc_verifier": verifier}
    )

    params = {
        "client_id": client_id(),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Google only returns the account chooser when asked; without it a user with one
        # session is silently signed straight back in after logging out.
        "prompt": "select_account",
    }
    return RedirectResponse(
        f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}", status_code=302
    )


def _fail(request: Request, reason: str) -> RedirectResponse:
    """Clear any half-built session and send the user back to a signed-out app."""
    request.session.clear()
    return RedirectResponse(f"/?error={reason}", status_code=302)


def _clear_oidc_session(request: Request) -> None:
    """Remove OIDC flow state without touching an authenticated user's session."""
    request.session.pop("oidc_state", None)
    request.session.pop("oidc_nonce", None)
    request.session.pop("oidc_verifier", None)


@router.get("/callback")
def callback(request: Request) -> RedirectResponse:
    """Complete the flow: verify state, exchange the code, verify the ID token."""
    state = request.query_params.get("state")
    expected_state = request.session.get("oidc_state")

    # Unsolicited callback: no OIDC flow was started from this session. Reject without
    # clearing any authenticated user's session — this prevents a forced-logout attack
    # where an attacker links a signed-in user to /api/auth/callback?error=x.
    if not expected_state:
        return RedirectResponse("/?error=invalid_request", status_code=302)

    # State mismatch: the callback does not match the flow this session started. Clear
    # OIDC state but preserve any authenticated user's session.
    if not state or not secrets.compare_digest(state, expected_state):
        _clear_oidc_session(request)
        return RedirectResponse("/?error=state_mismatch", status_code=302)

    # State validated — this is a legitimate OIDC callback from a flow this session
    # started. Pop OIDC state now and allow _fail() to clear the full session on errors.
    nonce = request.session.pop("oidc_nonce", None)
    verifier = request.session.pop("oidc_verifier", None)
    _clear_oidc_session(request)

    # Google reports user-facing refusals (consent denied, org_internal) as ?error=.
    if request.query_params.get("error"):
        return _fail(request, "access_denied")

    code = request.query_params.get("code")
    if not code:
        return _fail(request, "invalid_request")

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": verifier or "",
            },
            timeout=10,
        )
    except requests.RequestException:
        return _fail(request, "token_exchange_failed")

    if token_response.status_code != 200:
        return _fail(request, "token_exchange_failed")

    try:
        raw_id_token = token_response.json().get("id_token")
    except ValueError:
        return _fail(request, "token_exchange_failed")
    if not raw_id_token:
        return _fail(request, "no_id_token")

    try:
        # Checks the RS256 signature against Google's published certs, the issuer, the
        # expiry, and that `aud` is this client. Everything below is what it leaves out.
        claims = id_token.verify_oauth2_token(raw_id_token, _auth_request, client_id())
    except GoogleAuthError, ValueError:
        return _fail(request, "invalid_token")

    if claims.get("iss") not in GOOGLE_ISSUERS:
        return _fail(request, "invalid_issuer")

    # Binds this ID token to the login request that started the flow. google-auth does
    # not check nonce, so skipping it would leave a token-replay hole open.
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        return _fail(request, "nonce_mismatch")

    email = str(claims.get("email", "")).lower()
    # An unverified address proves nothing about who controls it, so it can never match
    # the allowlist meaningfully — reject before comparing.
    if not email or not claims.get("email_verified"):
        return _fail(request, "email_unverified")

    if email not in allowed_emails():
        return _fail(request, "not_authorized")

    request.session.clear()
    request.session["user"] = {
        "sub": claims["sub"],
        "email": email,
        "name": claims.get("name", ""),
        "picture": claims.get("picture", ""),
    }
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def authenticated(request: Request) -> dict:
    """FastAPI dependency: the signed-in user, or 401.

    Verifying the session cookie is local HMAC work, so unlike verifying a Google ID
    token per request this makes no network call.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Re-checked on every request so that removing someone from ALLOWED_EMAILS locks
    # them out on their next call instead of whenever their cookie happens to expire.
    if user.get("email", "").lower() not in allowed_emails():
        raise HTTPException(status_code=403, detail="Not authorized")
    return user
