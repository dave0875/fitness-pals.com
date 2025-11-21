"""Garmin OAuth connect/callback endpoints (OAuth-only, no credentials)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import User
from app.services.providers import ProviderTokenDetails, save_user_provider_token

router = APIRouter(prefix="/api/providers/garmin", tags=["garmin"])

GARMIN_CLIENT_ID = os.environ.get("GARMIN_CLIENT_ID")
GARMIN_CLIENT_SECRET = os.environ.get("GARMIN_CLIENT_SECRET")
GARMIN_REDIRECT_URI = os.environ.get("GARMIN_REDIRECT_URI")
GARMIN_AUTH_URL = (
    os.environ.get("GARMIN_AUTH_URL")
    or "https://connect.garmin.com/oauth-confirm"
)
GARMIN_TOKEN_URL = (
    os.environ.get("GARMIN_TOKEN_URL")
    or "https://connect.garmin.com/oauth/token"
)
GARMIN_SCOPE = os.environ.get("GARMIN_SCOPE") or "activity profile"


def _require_env():
    if not GARMIN_CLIENT_ID or not GARMIN_CLIENT_SECRET or not GARMIN_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Garmin OAuth env not configured (GARMIN_CLIENT_ID/SECRET/REDIRECT_URI)",
        )


@router.get("/login")
def garmin_login(_: User = Depends(get_current_user)):
    """Redirect the authenticated user to Garmin OAuth."""
    _require_env()
    params = {
        "response_type": "code",
        "client_id": GARMIN_CLIENT_ID,
        "redirect_uri": GARMIN_REDIRECT_URI,
        "scope": GARMIN_SCOPE,
    }
    url = requests.Request("GET", GARMIN_AUTH_URL, params=params).prepare().url
    return RedirectResponse(url)


def _resolve_tenant(user: User) -> Optional[UUID]:
    """Return a tenant id if the user model carries one; otherwise None."""
    return getattr(user, "tenant_id", None)


@router.get("/callback")
def garmin_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange Garmin auth code for tokens and persist them securely."""
    _require_env()
    if error:
        raise HTTPException(status_code=400, detail=f"Garmin auth failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": GARMIN_REDIRECT_URI,
        "client_id": GARMIN_CLIENT_ID,
        "client_secret": GARMIN_CLIENT_SECRET,
    }
    resp = requests.post(GARMIN_TOKEN_URL, data=data, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail="Garmin token exchange failed",
        )
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in") or payload.get("expires")  # seconds
    if not access_token:
        raise HTTPException(status_code=400, detail="Garmin token exchange missing access token")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            expires_at = None

    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=_resolve_tenant(user),
            provider="garmin",
            access_token=access_token,
            refresh_token=refresh_token,
            scope=payload.get("scope"),
            provider_user_id=payload.get("user_id"),
            expires_at=expires_at,
            metadata={"token_received_at": datetime.utcnow().isoformat()},
        ),
    )
    return {"status": "connected", "provider": "garmin"}
