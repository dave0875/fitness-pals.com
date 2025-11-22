"""Token status endpoints for auth providers."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
settings = get_settings()


@router.get("/token-status/google")
def google_token_status(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    """Return metadata about the provided Google OAuth token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credentials missing",
        )
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google client id not configured",
        )
    token = credentials.credentials
    try:
        request_obj = google_requests.Request()
        claims = google_id_token.verify_oauth2_token(
            token,
            request_obj,
            settings.google_client_id,
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
    email = claims.get("email")
    exp = claims.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp, timezone.utc) if exp else None
    )
    now = datetime.now(timezone.utc)
    seconds_remaining = (
        int((expires_at - now).total_seconds()) if expires_at else None
    )
    status_str = (
        "active"
        if expires_at is None or (seconds_remaining is not None and seconds_remaining > 0)
        else "expired"
    )
    if seconds_remaining is not None and seconds_remaining < 0:
        seconds_remaining = 0
    return {
        "status": status_str,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "seconds_remaining": seconds_remaining,
        "user_email": email,
    }
