"""Encryption helpers for JWTs and provider tokens."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from cryptography.fernet import Fernet
from fastapi.responses import Response

from app.config import get_settings

settings = get_settings()
fernet = Fernet(settings.fernet_key.encode())
APP_SESSION_COOKIE = "runtrainer_session"
APP_REFRESH_COOKIE = "runtrainer_refresh"
APP_REFRESH_COOKIE_PATH = "/auth"


class InvalidAppToken(ValueError):
    """Raised when an app JWT fails its complete purpose-specific contract."""


def _create_token(
    user_id: uuid.UUID,
    *,
    purpose: str,
    audience: str,
    expires_delta: timedelta,
    jti: uuid.UUID | None = None,
    issued_at: datetime | None = None,
) -> str:
    now = issued_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": int((now + expires_delta).timestamp()),
        "iat": int(now.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": audience,
        "jti": str(jti or uuid.uuid4()),
        "typ": purpose,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: uuid.UUID,
    *,
    jti: uuid.UUID | None = None,
    issued_at: datetime | None = None,
) -> str:
    """Issue a short-lived access token for API requests."""
    return _create_token(
        user_id,
        purpose="access",
        audience=settings.jwt_access_audience,
        expires_delta=timedelta(minutes=settings.access_token_exp_minutes),
        jti=jti,
        issued_at=issued_at,
    )


def create_refresh_token(
    user_id: uuid.UUID,
    *,
    jti: uuid.UUID | None = None,
    issued_at: datetime | None = None,
) -> str:
    """Issue a longer-lived refresh token."""
    return _create_token(
        user_id,
        purpose="refresh",
        audience=settings.jwt_refresh_audience,
        expires_delta=timedelta(days=settings.refresh_token_exp_days),
        jti=jti,
        issued_at=issued_at,
    )


def _decode_token(token: str, *, purpose: str, audience: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=audience,
            options={
                "require_sub": True,
                "require_exp": True,
                "require_iat": True,
                "require_iss": True,
                "require_aud": True,
                "require_jti": True,
            },
        )
        if claims.get("typ") != purpose or claims.get("aud") != audience:
            raise InvalidAppToken("wrong token purpose")
        if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("jti"), str):
            raise InvalidAppToken("invalid token identifier")
        uuid.UUID(claims["sub"])
        uuid.UUID(claims["jti"])
        for timestamp_claim in ("iat", "exp"):
            value = claims.get(timestamp_claim)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidAppToken("invalid token timestamp")
    except (JWTError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidAppToken):
            raise
        raise InvalidAppToken("invalid app token") from exc
    return dict(claims)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode an app access credential, rejecting every other JWT purpose."""
    return _decode_token(
        token,
        purpose="access",
        audience=settings.jwt_access_audience,
    )


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode an app refresh credential, rejecting every other JWT purpose."""
    return _decode_token(
        token,
        purpose="refresh",
        audience=settings.jwt_refresh_audience,
    )


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Attach app-issued auth cookies to a response."""
    response.set_cookie(
        APP_SESSION_COOKIE,
        access_token,
        max_age=settings.access_token_exp_minutes * 60,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        APP_REFRESH_COOKIE,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        APP_REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_exp_days * 24 * 60 * 60,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path=APP_REFRESH_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    """Expire both app-issued authentication cookies."""
    response.delete_cookie(
        APP_SESSION_COOKIE,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        APP_REFRESH_COOKIE,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path=APP_REFRESH_COOKIE_PATH,
    )
    response.delete_cookie(
        APP_REFRESH_COOKIE,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )


def encrypt_token(raw: str) -> bytes:
    """Encrypt a sensitive token for persistence."""
    return fernet.encrypt(raw.encode())


def decrypt_token(token: bytes) -> str:
    """Decrypt a token previously encrypted by encrypt_token."""
    return fernet.decrypt(token).decode()
