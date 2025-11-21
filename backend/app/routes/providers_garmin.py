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
from pydantic import BaseModel
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.services.garmin_ingest import fetch_garmin_recent
from app.services.garmin_scheduler import fetch_all as fetch_all_users

router = APIRouter(prefix="/api/providers/garmin", tags=["garmin"])

def _config():
    return {
        "client_id": os.environ.get("GARMIN_CLIENT_ID"),
        "client_secret": os.environ.get("GARMIN_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("GARMIN_REDIRECT_URI"),
        "auth_url": os.environ.get("GARMIN_AUTH_URL")
        or "https://connect.garmin.com/oauth-confirm",
        "token_url": os.environ.get("GARMIN_TOKEN_URL")
        or "https://connect.garmin.com/oauth/token",
        "scope": os.environ.get("GARMIN_SCOPE") or "activity profile",
    }


def _require_env():
    cfg = _config()
    if not cfg["client_id"] or not cfg["client_secret"] or not cfg["redirect_uri"]:
        raise HTTPException(
            status_code=500,
            detail="Garmin OAuth env not configured (GARMIN_CLIENT_ID/SECRET/REDIRECT_URI)",
        )
    return cfg


@router.get("/login")
def garmin_login(_: User = Depends(get_current_user)):
    """Redirect the authenticated user to Garmin OAuth."""
    cfg = _require_env()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scope"],
    }
    url = requests.Request("GET", cfg["auth_url"], params=params).prepare().url
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
    cfg = _require_env()
    if error:
        raise HTTPException(status_code=400, detail=f"Garmin auth failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    resp = requests.post(cfg["token_url"], data=data, timeout=10)
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


def _refresh_tokens(refresh_token: str):
    cfg = _require_env()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    resp = requests.post(cfg["token_url"], data=data, timeout=10)
    if resp.status_code in (400, 401):
        return None
    if resp.status_code != 200:
        return None
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    access_token = payload.get("access_token")
    if not access_token:
        return None
    refresh_rotated = payload.get("refresh_token") or refresh_token
    expires_in = payload.get("expires_in") or payload.get("expires")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            expires_at = None
    return access_token, refresh_rotated, expires_at, payload


@router.post("/refresh")
def garmin_refresh(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Refresh Garmin tokens or signal reauth when refresh fails or missing."""
    _require_env()
    token = get_user_provider_token(db, user.id, "garmin", getattr(user, "tenant_id", None))
    if not token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    decrypted = decrypt_user_tokens(token)
    refresh_token = decrypted.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    result = _refresh_tokens(refresh_token)
    if not result:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    access_token, new_refresh, expires_at, payload = result
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=getattr(user, "tenant_id", None),
            provider="garmin",
            access_token=access_token,
            refresh_token=new_refresh,
            scope=payload.get("scope"),
            provider_user_id=payload.get("user_id"),
            expires_at=expires_at,
            metadata={"token_received_at": datetime.utcnow().isoformat()},
        ),
    )
    return {"status": "refreshed"}


@router.post("/fetch")
def garmin_fetch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch recent Garmin data for the current user."""
    try:
        run = fetch_garmin_recent(db, user)
        return {"status": "ok", "ingested": run.summary.get("fetched", 0) if run.summary else 0}
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Garmin fetch failed") from exc


@router.post("/fetch/all")
def garmin_fetch_all(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch recent Garmin data for all users with Garmin tokens."""
    try:
        summary = fetch_all_users(db)
        return summary
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Garmin batch fetch failed") from exc


class ScraperTokenRequest(BaseModel):
    """Body for supplying a scraper access token (no credentials)."""

    scraper_access_token: str
    expires_at: Optional[datetime] = None


@router.post("/scraper/token")
def garmin_scraper_token(
    body: ScraperTokenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store a scraper access token (no username/password accepted)."""
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=getattr(user, "tenant_id", None),
            provider="garmin_scraper",
            access_token=body.scraper_access_token,
            refresh_token=None,
            scope="scraper",
            provider_user_id=None,
            expires_at=body.expires_at,
            metadata={"token_received_at": datetime.utcnow().isoformat(), "mode": "scraper"},
        ),
    )
    return {"status": "ok", "provider": "garmin_scraper"}
