"""Encryption helpers for JWTs and provider tokens."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from jose import jwt
from cryptography.fernet import Fernet
from fastapi.responses import Response

from app.config import get_settings

settings = get_settings()
fernet = Fernet(settings.fernet_key.encode())
APP_SESSION_COOKIE = "runtrainer_session"
APP_REFRESH_COOKIE = "runtrainer_refresh"


def create_jwt_token(subject: str, expires_delta: timedelta) -> str:
    """Create a signed JWT for the given subject and expiry window."""
    expire = datetime.utcnow() + expires_delta
    payload: Dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    """Issue a short-lived access token for API requests."""
    return create_jwt_token(str(user_id), timedelta(minutes=settings.access_token_exp_minutes))


def create_refresh_token(user_id: uuid.UUID) -> str:
    """Issue a longer-lived refresh token."""
    return create_jwt_token(str(user_id), timedelta(days=settings.refresh_token_exp_days))


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
    response.set_cookie(
        APP_REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_exp_days * 24 * 60 * 60,
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
