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

Machine callers take a second path. A service account has no browser to be redirected,
so it never reaches the callback and never gets a cookie; instead it presents a
Google-signed ID token as a bearer credential, checked against ALLOWED_SERVICE_ACCOUNTS.
That list is deliberately separate from ALLOWED_EMAILS, and empty by default, so this
path stays off until someone turns it on.
"""

import base64
import os
import secrets
import time
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


def app_base_url() -> str:
    """Public origin of the app. Read per-call, for the same reason as client_id()."""
    return os.environ.get("APP_BASE_URL", "http://localhost:3000").rstrip("/")


def redirect_uri() -> str:
    """Where Google sends the user back.

    Must match a registered redirect URI on the OAuth client exactly, including scheme
    and port — a mismatch is Google's "Error 400: redirect_uri_mismatch".
    """
    return f"{app_base_url()}/api/auth/callback"


def cookie_secure() -> bool:
    """Whether to set the session cookie's Secure flag.

    Derived from APP_BASE_URL so there is one switch to get wrong instead of two —
    `http://localhost:3000` in dev turns it off, which the browser requires for a cookie
    to stick over plain http.
    """
    return app_base_url().startswith("https://")


# How many concurrent sign-in attempts one browser may have in flight, and how long each
# stays valid. Both are small on purpose: the entries live in the session cookie, which
# browsers cap around 4KB, and a started-but-never-finished flow is worthless quickly.
PENDING_MAX = 5
PENDING_TTL_SECONDS = 10 * 60


def _prune_pending(pending: dict) -> dict:
    """Drop expired pending flows and keep only the newest PENDING_MAX."""
    now = time.time()
    fresh = {
        state: flow
        for state, flow in pending.items()
        if now - flow.get("ts", 0) < PENDING_TTL_SECONDS
    }
    if len(fresh) > PENDING_MAX:
        newest = sorted(fresh.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
        fresh = dict(newest[:PENDING_MAX])
    return fresh


def _take_pending(session, state: str) -> dict | None:
    """Remove and return the pending flow matching `state`, or None.

    Compared with compare_digest rather than a dict lookup to keep the state check off
    the timing side channel, the same property the single-tuple version had.
    """
    pending = session.get("oidc_pending", {})
    for candidate in list(pending):
        if secrets.compare_digest(candidate, state):
            flow = pending.pop(candidate)
            session["oidc_pending"] = pending
            return flow
    return None


_auth_request = google_requests.Request()


def allowed_emails() -> frozenset[str]:
    """The set of addresses permitted to sign in, lowercased.

    Read per-call rather than at import so tests can set it with monkeypatch.
    """
    raw = os.environ.get("ALLOWED_EMAILS", "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def allowed_service_accounts() -> frozenset[str]:
    """The service accounts permitted to call the API with a bearer token, lowercased.

    Kept separate from ALLOWED_EMAILS rather than folded into it so the two credentials
    stay independently grantable: adding a colleague to the sign-in list must not also
    hand out machine access, and authorizing a batch job must not create an identity that
    can sign in and browse. Empty — the default — turns bearer auth off entirely.
    """
    raw = os.environ.get("ALLOWED_SERVICE_ACCOUNTS", "")
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

    # Keyed by state rather than kept as one tuple, so signing in from two tabs does not
    # have the second attempt overwrite the first and break both.
    #
    # The session cookie is signed, so the browser can read these but cannot forge them.
    # That is the property state and nonce need; the PKCE verifier is the client's own
    # secret by design, so holding it client-side is what RFC 7636 intends.
    pending = request.session.get("oidc_pending", {})
    pending[state] = {"nonce": nonce, "verifier": verifier, "ts": time.time()}
    # Pruned after inserting, so the cap counts this attempt and the newest always wins.
    request.session["oidc_pending"] = _prune_pending(pending)

    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
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


def _fail(reason: str) -> RedirectResponse:
    """Abandon this sign-in attempt.

    Deliberately does not touch the session beyond the pending entry the caller already
    removed. Clearing it wholesale would let anyone log a signed-in user out by linking
    them to a failing callback, since SameSite=Lax still sends the cookie on a top-level
    GET.
    """
    return RedirectResponse(f"/?error={reason}", status_code=302)


@router.get("/callback")
def callback(request: Request) -> RedirectResponse:
    """Complete the flow: match the state, exchange the code, verify the ID token."""
    state = request.query_params.get("state")
    flow = _take_pending(request.session, state) if state else None

    # No matching pending flow means this callback was not solicited by this browser —
    # a stale retry, a replay, or someone else's link. Leave the session exactly as it
    # was and say nothing about why.
    if flow is None:
        return RedirectResponse("/", status_code=302)

    # Google reports user-facing refusals (consent denied, org_internal) as ?error=.
    # Checked after the state match so only a flow we started can surface an error.
    if request.query_params.get("error"):
        return _fail("access_denied")

    nonce = flow.get("nonce")
    verifier = flow.get("verifier")

    code = request.query_params.get("code")
    if not code:
        return _fail("invalid_request")

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier or "",
            },
            timeout=10,
        )
    except requests.RequestException:
        return _fail("token_exchange_failed")

    if token_response.status_code != 200:
        return _fail("token_exchange_failed")

    try:
        raw_id_token = token_response.json().get("id_token")
    except ValueError:
        return _fail("token_exchange_failed")
    if not raw_id_token:
        return _fail("no_id_token")

    try:
        # Checks the RS256 signature against Google's published certs, the issuer, the
        # expiry, and that `aud` is this client. Everything below is what it leaves out.
        claims = id_token.verify_oauth2_token(raw_id_token, _auth_request, client_id())
    except GoogleAuthError, ValueError:
        return _fail("invalid_token")

    if claims.get("iss") not in GOOGLE_ISSUERS:
        return _fail("invalid_issuer")

    # Binds this ID token to the login request that started the flow. google-auth does
    # not check nonce, so skipping it would leave a token-replay hole open.
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        return _fail("nonce_mismatch")

    email = str(claims.get("email", "")).lower()
    # An unverified address proves nothing about who controls it, so it can never match
    # the allowlist meaningfully — reject before comparing.
    if not email or not claims.get("email_verified"):
        return _fail("email_unverified")

    if email not in allowed_emails():
        return _fail("not_authorized")

    # Start the authenticated session from empty. This also drops any other pending
    # flows, which is intended: once signed in, a sibling tab's callback has nothing
    # left to do and lands on "/" already authenticated.
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


def _bearer_token(request: Request) -> str | None:
    """The credential from an `Authorization: Bearer …` header, if there is one."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _service_account(request: Request) -> dict | None:
    """The service account behind this request's bearer token, or None.

    Every rejection returns None rather than a distinct error. The caller turns that into
    a flat 401, so an unauthenticated client cannot tell a token that failed verification
    from one that verified but is not on the list — the session path can afford to
    distinguish those (403) because reaching it already required a valid cookie.
    """
    allowed = allowed_service_accounts()
    # Checked before the header so the default configuration does no verification work
    # at all, and an unconfigured deployment cannot be probed through this path.
    if not allowed:
        return None

    raw = _bearer_token(request)
    if not raw:
        return None

    try:
        # Same verification the callback does, with one difference that carries the
        # weight here: the audience is this app's own origin, not the OAuth client. A
        # service account token is minted for a target_audience, so requiring ours is
        # what stops a token issued for some other service from being replayed at us.
        #
        # Unlike the session path this runs per request, against Google's certs. The
        # library caches them, so the steady-state cost is a signature check, not a fetch.
        claims = id_token.verify_oauth2_token(raw, _auth_request, app_base_url())
    except GoogleAuthError, ValueError:
        return None

    if claims.get("iss") not in GOOGLE_ISSUERS:
        return None

    email = str(claims.get("email", "")).lower()
    if not email or not claims.get("email_verified"):
        return None
    if email not in allowed:
        return None

    # Shaped like the session user so downstream code cannot accidentally depend on which
    # credential got it here. Nothing reads `service_account`; it is there for logging and
    # for the day some route needs to refuse a machine caller.
    return {
        "sub": claims["sub"],
        "email": email,
        "name": email,
        "picture": "",
        "service_account": True,
    }


def authenticated(request: Request) -> dict:
    """FastAPI dependency: the caller's identity, or 401.

    Two credentials are accepted. The session cookie covers every browser request and is
    local HMAC work, so it is tried first and costs nothing. A bearer ID token is the
    fallback, for callers that have no browser to complete the OIDC redirect with.
    """
    user = request.session.get("user")
    if not user:
        service_account = _service_account(request)
        if service_account is not None:
            return service_account
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Re-checked on every request so that removing someone from ALLOWED_EMAILS locks
    # them out on their next call instead of whenever their cookie happens to expire.
    if user.get("email", "").lower() not in allowed_emails():
        raise HTTPException(status_code=403, detail="Not authorized")
    return user
