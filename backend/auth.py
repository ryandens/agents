from datetime import UTC, datetime, timedelta
import os
from typing import Any

import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    sub: str
    email: str
    name: str | None = None
    picture: str | None = None


class GoogleCredentialRequest(BaseModel):
    credential: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthenticatedUser


def auth_enabled() -> bool:
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID"))


def _get_signing_secret() -> str:
    secret = os.getenv("APP_AUTH_SECRET")
    if secret:
        return secret
    # Local-only fallback for development. Override in production.
    return "dev-auth-secret-change-me"


def verify_google_credential(credential: str) -> AuthenticatedUser:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_OAUTH_CLIENT_ID is not configured",
        )

    try:
        payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credential",
        ) from exc

    email = payload.get("email")
    sub = payload.get("sub")
    if not email or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account did not include required claims",
        )

    return AuthenticatedUser(
        sub=sub,
        email=email,
        name=payload.get("name"),
        picture=payload.get("picture"),
    )


def create_access_token(user: AuthenticatedUser) -> str:
    expiry_hours = int(os.getenv("APP_AUTH_TOKEN_HOURS", "12"))
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expiry_hours)).timestamp()),
    }
    return jwt.encode(payload, _get_signing_secret(), algorithm="HS256")


def decode_access_token(token: str) -> AuthenticatedUser:
    try:
        payload = jwt.decode(token, _get_signing_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token claims",
        )

    return AuthenticatedUser(
        sub=sub,
        email=email,
        name=payload.get("name"),
        picture=payload.get("picture"),
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthenticatedUser | None:
    if not auth_enabled():
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return decode_access_token(credentials.credentials)
