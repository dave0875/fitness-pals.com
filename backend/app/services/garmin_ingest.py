"""Minimal Garmin ingestion helper using stored OAuth tokens."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import IngestRun
from app.services import dedupe
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.routes import providers_garmin


def _api_base() -> str:
    return os.environ.get("GARMIN_API_BASE") or "https://api.garmin.com"


def _mode() -> str:
    return (os.environ.get("GARMIN_MODE") or "oauth").lower()


def _ensure_fresh_tokens(db: Session, user, token_row) -> dict:
    tokens = decrypt_user_tokens(token_row)
    expires_at: Optional[datetime] = tokens.get("expires_at")
    if expires_at and expires_at > datetime.utcnow() + timedelta(minutes=5):
        return tokens
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    refreshed = providers_garmin._refresh_tokens(refresh_token)  # pylint: disable=protected-access
    if not refreshed:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    access_token, new_refresh, new_expires_at, payload = refreshed
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
            expires_at=new_expires_at,
            metadata={"token_received_at": datetime.utcnow().isoformat()},
        ),
    )
    tokens = tokens.copy()
    tokens["access_token"] = access_token
    tokens["refresh_token"] = new_refresh
    tokens["expires_at"] = new_expires_at
    return tokens


def fetch_garmin_recent(db: Session, user) -> IngestRun:
    """Fetch recent Garmin activities and record an ingest run summary."""
    mode = _mode()
    provider_key = "garmin" if mode == "oauth" else "garmin_scraper"
    token_row = get_user_provider_token(db, user.id, provider_key, getattr(user, "tenant_id", None))
    if not token_row:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    if mode == "oauth":
        tokens = _ensure_fresh_tokens(db, user, token_row)
    else:
        tokens = decrypt_user_tokens(token_row)
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    cfg = providers_garmin._config()  # pylint: disable=protected-access
    resp = requests.get(
        f"{_api_base().rstrip('/')}/activities",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code == 401:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Garmin fetch failed")
    activities = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else []
    run = dedupe.record_ingest_run(db, provider="garmin")
    summary = {"fetched": len(activities)}
    dedupe.finish_ingest_run(db, run, status="completed", summary=summary)
    return run
