"""Garmin OAuth connect/callback endpoints (OAuth-only, no credentials)."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import garth

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
logger = logging.getLogger("garmin.routes")


def _redact_token(token: Optional[str]) -> str:
    """Return a short hint of a token without exposing full value."""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"

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


@router.get("/token-status")
def garmin_token_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return metadata about the stored Garmin token for the current user."""
    tenant_id = _resolve_tenant(user)
    token = get_user_provider_token(db, user.id, "garmin", tenant_id)
    mode = "oauth"
    if not token:
        token = get_user_provider_token(db, user.id, "garmin_scraper", tenant_id)
        mode = "scraper" if token else None
    if not token:
        logger.info(
            "garmin token status: missing",
            extra={"user_id": str(user.id), "tenant_id": str(tenant_id) if tenant_id else None},
        )
        return {
            "status": "missing",
            "expires_at": None,
            "seconds_remaining": None,
            "provider_user_id": None,
            "refresh_token_present": False,
            "mode": None,
        }
    expires_dt = token.expires_at
    if expires_dt and expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    seconds_remaining = (
        int((expires_dt - now).total_seconds()) if expires_dt else None
    )
    # Allow small clock skew (~5m) before marking tokens as expired to avoid false negatives right after issue.
    if seconds_remaining is not None and seconds_remaining < -300:
        status_str = "expired"
    else:
        status_str = "active"
    if seconds_remaining is not None and seconds_remaining < 0:
        seconds_remaining = 0
    response = {
        "status": status_str,
        "expires_at": expires_dt.isoformat() if expires_dt else None,
        "seconds_remaining": seconds_remaining,
        "provider_user_id": str(token.provider_user_id) if token.provider_user_id else None,
        "refresh_token_present": bool(token.refresh_token_encrypted),
        "mode": mode,
    }
    logger.info(
        "garmin token status",
        extra={
            "user_id": str(user.id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "mode": mode,
            "expires_at": response["expires_at"],
            "seconds_remaining": seconds_remaining,
            "status": status_str,
            "provider_user_id": response["provider_user_id"],
            "has_refresh": response["refresh_token_present"],
        },
    )
    return response


class ScraperTokenRequest(BaseModel):
    """Body for supplying a scraper access token (no credentials)."""

    scraper_access_token: str
    expires_at: Optional[datetime] = None
    token_secret: Optional[str] = None


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
            metadata={
                "token_received_at": datetime.utcnow().isoformat(),
                "mode": "scraper",
                "token_secret": body.token_secret,
            },
        ),
    )
    return {"status": "ok", "provider": "garmin_scraper"}


class GarminAcquireTokenRequest(BaseModel):
    """Incoming credentials used to acquire Garmin OAuth tokens (not stored)."""

    username: str
    password: str
    expires_at: Optional[datetime] = None


@router.post("/acquire-token")
def garmin_acquire_token(
    body: GarminAcquireTokenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange Garmin credentials for tokens without storing credentials."""
    mode = (os.environ.get("GARMIN_MODE") or "oauth").lower()
    provider_name = "garmin" if mode == "oauth" else "garmin_scraper"
    client = garth.Client()
    username = body.username
    password = body.password
    try:
        client.login(username, password)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail="Garmin login failed") from exc
    finally:
        # Immediately clear sensitive values from memory
        body.password = ""
        password = ""
    oauth2 = getattr(client, "oauth2_token", None)
    oauth1 = getattr(client, "oauth1_token", None)
    access_token = None
    refresh_token = None
    token_secret = None
    if mode == "scraper":
        if not oauth1:
            raise HTTPException(status_code=400, detail="Garmin did not return scraper tokens")
        access_token = getattr(oauth1, "oauth_token", None)
        token_secret = getattr(oauth1, "oauth_token_secret", None)
    else:
        if not oauth2:
            raise HTTPException(status_code=400, detail="Garmin did not return OAuth tokens")
        access_token = getattr(oauth2, "access_token", None) or oauth2.get("access_token")
        refresh_token = getattr(oauth2, "refresh_token", None) or oauth2.get("refresh_token")
    expires_at = body.expires_at
    if not expires_at:
        exp_ts = getattr(oauth2, "expires_at", None) if oauth2 else None
        if not exp_ts and oauth2:
            exp_ts = oauth2.get("expires_at")
        if isinstance(exp_ts, (int, float)):
            expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        elif isinstance(exp_ts, datetime):
            expires_at = exp_ts
        elif oauth2:
            expires_in = getattr(oauth2, "expires_in", None) or oauth2.get("expires_in")
            if isinstance(expires_in, (int, float)):
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    if not access_token or (mode == "oauth" and not refresh_token):
        raise HTTPException(status_code=400, detail="Garmin tokens incomplete")
    scope_val = getattr(oauth2, "scope", None) if oauth2 else None
    if not scope_val and oauth2:
        scope_val = oauth2.get("scope")
    refresh_present = bool(refresh_token)
    metadata = {
        "token_received_at": datetime.utcnow().isoformat(),
    }
    if token_secret:
        metadata["token_secret"] = token_secret
    logger.info(
        "garmin acquire token success",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "mode": mode,
            "provider": provider_name,
            "access_hint": _redact_token(access_token),
            "refresh_hint": _redact_token(refresh_token),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "has_refresh": refresh_present,
            "scope": scope_val,
        },
    )
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=_resolve_tenant(user),
            provider=provider_name,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope_val,
            provider_user_id=None,
            expires_at=expires_at,
            metadata=metadata,
        ),
    )
    return {
        "status": "ok",
        "expires_at": expires_at.isoformat() if expires_at else None,
        "refresh_token_present": refresh_present,
    }


@router.post("/refresh-token")
def garmin_refresh_token(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh the stored Garmin OAuth token when refresh_token is present."""
    tenant_id = _resolve_tenant(user)
    token_row = get_user_provider_token(db, user.id, "garmin", tenant_id)
    if not token_row or not token_row.refresh_token_encrypted:
        raise HTTPException(status_code=400, detail="No refresh token stored")
    tokens = decrypt_user_tokens(token_row)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token missing")
    cfg = _require_env()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    try:
        resp = requests.post(cfg["token_url"], data=data, timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Garmin refresh failed") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Garmin refresh rejected")
    payload = resp.json()
    access_token = payload.get("access_token")
    new_refresh = payload.get("refresh_token") or refresh_token
    expires_in = payload.get("expires_in")
    expires_at = token_row.expires_at
    if isinstance(expires_in, (int, float)):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    if not access_token:
        raise HTTPException(status_code=400, detail="Garmin refresh missing access token")
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=tenant_id,
            provider="garmin",
            access_token=access_token,
            refresh_token=new_refresh,
            scope=payload.get("scope") or tokens.get("scope"),
            provider_user_id=token_row.provider_user_id,
            expires_at=expires_at,
            metadata={"token_received_at": datetime.utcnow().isoformat()},
        ),
    )
    return {
        "status": "ok",
        "expires_at": expires_at.isoformat() if expires_at else None,
        "refresh_token_present": True,
    }
