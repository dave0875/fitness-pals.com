"""Garmin OAuth connect/callback endpoints (OAuth-only, no credentials)."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func
import requests
from sqlalchemy.orm import Session
import garth

from app.deps import get_current_user
from app.db import get_db
from app.models import User, Activity, IngestRun, IngestDecision
from pydantic import BaseModel
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.services.garmin_ingest import fetch_garmin_recent
from app.services.garmin_scheduler import fetch_all as fetch_all_users
from app.services import garmin_ingest
from app.services.influx import get_influx_client_for_user, get_user_datasource
from app.services.garmin_fetchers import CONNECTAPI_SOURCES, STAT_FETCHERS
from app.utils.security import decrypt_token

router = APIRouter(prefix="/api/providers/garmin", tags=["garmin"])
logger = logging.getLogger("garmin.routes")
logger.setLevel(logging.INFO)


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


def _capture_provider_user_id(
    db: Session,
    token_row,
    access_token: Optional[str],
    token_secret: Optional[str] = None,
    fallback_provider_user_id: Optional[str] = None,
):
    """
    Best-effort fetch of provider_user_id for scraper tokens so status panels show the id.
    Non-fatal; only used for oauth1/scraper tokens.
    """
    if not token_row or token_row.provider_user_id or not access_token:
        return
    try:
        client = garth.Client()
        client.oauth1_token = SimpleNamespace(
            oauth_token=access_token,
            oauth_token_secret=token_secret or "",
            mfa_token=None,
            mfa_expiration_timestamp=None,
            domain="garmin.com",
        )
        profile = client.connectapi("user-service/user/profile")
        provider_user_id = (
            profile.get("userId")
            or profile.get("displayName")
            or profile.get("username")
        )
        if provider_user_id:
            token_row.provider_user_id = str(provider_user_id)
            db.commit()
            db.refresh(token_row)
            logger.info(
                "garmin provider_user_id captured",
                extra={"provider_user_id": token_row.provider_user_id},
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "failed to fetch provider_user_id for garmin token",
            extra={"error": str(exc)},
            exc_info=True,
        )
    if fallback_provider_user_id and not token_row.provider_user_id:
        token_row.provider_user_id = str(fallback_provider_user_id)
        db.commit()
        db.refresh(token_row)
        logger.info(
            "garmin provider_user_id set from fallback",
            extra={"provider_user_id": token_row.provider_user_id},
        )


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
def garmin_fetch(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    test_run: bool = False,
):
    """Fetch recent Garmin data for the current user."""
    try:
        run = fetch_garmin_recent(db, user, test_run=test_run)
        # Build a simple integrity report
        activities_count = (
            db.query(Activity)
            .filter(Activity.user_id == user.id, Activity.ingest_run_id == run.id)
            .count()
        )
        summary = run.summary or {}
        report = {
            "activities_count": activities_count,
            "activity_gps_written": summary.get("activity_gps_written"),
            "timeseries_points": summary.get("timeseries_points"),
            "sleep_daily": summary.get("sleep_daily"),
            "vo2_daily": len(summary.get("vo2", {}).get("daily", [])) if summary.get("vo2") else 0,
        }
        # Optional Influx count for this run
        try:
            client = get_influx_client_for_user(db, user.id)
            tag = f"TEST_{run.id}" if test_run else str(run.id)
            flux = f'''
from(bucket: "{client.default_bucket}")
  |> range(start: 0)
  |> filter(fn: (r) => r.ingest_run_id == "{tag}")
  |> group(columns: ["_measurement"])
  |> count()
'''
            tables = client.query_api().query(org=client.org, query=flux)
            influx_counts = []
            for table in tables:
                for record in table.records:
                    influx_counts.append(
                        {"measurement": record.get_measurement(), "count": record.get_value()}
                    )
            report["influx_counts"] = influx_counts
        except Exception:
            pass
        # Human-readable summary for logs/clients that truncate JSON
        lines = [
            f"Activities: {activities_count}",
            f"ActivityGPS written: {summary.get('activity_gps_written')}",
            f"Timeseries points: {summary.get('timeseries_points')}",
            f"Sleep sessions: {summary.get('sleep_daily')}",
        ]
        influx_lines = []
        for ic in report.get("influx_counts") or []:
            influx_lines.append(f"{ic.get('measurement')}={ic.get('count')}")
        if influx_lines:
            lines.append("Influx: " + ", ".join(influx_lines))
        report["report_pretty"] = " | ".join(lines)
        return {
            "status": "ok",
            "ingested": summary.get("timeseries_points") or 0,
            "test_run": test_run,
            "ingest_run_tag": f"TEST_{run.id}" if test_run else str(run.id),
            "report": report,
        }
    except HTTPException as exc:
        logger.exception(
            "garmin fetch failed (http)",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "test_run": test_run,
                "status_code": getattr(exc, "status_code", None),
                "detail": getattr(exc, "detail", None),
            },
        )
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(
            "garmin fetch failed (unexpected)",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "test_run": test_run,
                "error": str(exc),
            },
        )
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
    provider: Optional[str] = None,
    include_all: bool = False,
):
    """Return metadata about the stored Garmin token for the current user."""
    tenant_id = _resolve_tenant(user)
    env_mode = (os.environ.get("GARMIN_MODE") or "oauth").lower()
    provider_key = provider or ("garmin" if env_mode == "oauth" else "garmin_scraper")
    token = get_user_provider_token(db, user.id, provider_key, tenant_id)
    if include_all:
        other = "garmin_scraper" if provider_key == "garmin" else "garmin"
        tokens = [
            serialize_token_status(token, provider_key, user, tenant_id),
            serialize_token_status(
                get_user_provider_token(db, user.id, other, tenant_id), other, user, tenant_id
            ),
        ]
        return {"providers": [t for t in tokens if t is not None]}
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
            "mode": env_mode,
            "provider": provider_key,
            "updated_at": None,
        }
    result = serialize_token_status(token, provider_key, user, tenant_id)
    return result


def serialize_token_status(token, provider_key: str, user: User, tenant_id: Optional[UUID]):
    if not token:
        return None
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
        "mode": "scraper" if provider_key == "garmin_scraper" else "oauth",
        "provider": provider_key,
        "updated_at": token.updated_at.isoformat() if getattr(token, "updated_at", None) else None,
    }
    if status_str == "expired":
        logger.info(
            "garmin token expired or expiring",
            extra={
                "user_id": str(user.id),
                "tenant_id": str(tenant_id) if tenant_id else None,
                "provider": provider_key,
                "expires_at": response["expires_at"],
                "now": now.isoformat(),
                "seconds_remaining": seconds_remaining,
            },
        )
    logger.info(
        "garmin token status",
        extra={
            "user_id": str(user.id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "provider": provider_key,
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
    token_row = save_user_provider_token(
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
    _capture_provider_user_id(db, token_row, body.scraper_access_token, body.token_secret)
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
    token_row = save_user_provider_token(
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
    if provider_name == "garmin_scraper":
        _capture_provider_user_id(
            db,
            token_row,
            access_token,
            token_secret,
            fallback_provider_user_id=username,
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


@router.get("/categories")
def list_garmin_categories(_: User = Depends(get_current_user)):
    """List validated Garmin categories (stats + connectapi) that can be probed."""
    stats = [{"key": k, "type": "stat"} for k in STAT_FETCHERS.keys()]
    connect = [
        {
            "key": k,
            "type": "connectapi",
            "per_day": v.get("per_day"),
            "path": v.get("path"),
            "params": v.get("params"),
            "method": v.get("method", "GET"),
        }
        for k, v in CONNECTAPI_SOURCES.items()
    ]
    return stats + connect


@router.post("/test-category")
def test_garmin_category(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Probe a single Garmin category using the stored token without writing to Influx."""
    category = payload.get("category")
    date = payload.get("date")
    path_override = payload.get("path")
    params_override = payload.get("params")
    method_override = payload.get("method")
    start_date_override = payload.get("start_date")
    end_date_override = payload.get("end_date")
    if not category:
        raise HTTPException(status_code=400, detail="category is required")
    mode = garmin_ingest._mode()  # pylint: disable=protected-access
    provider_key = "garmin" if mode == "oauth" else "garmin_scraper"
    token_row = get_user_provider_token(db, user.id, provider_key, getattr(user, "tenant_id", None))
    if not token_row:
        raise HTTPException(status_code=410, detail="Garmin token missing for probe")
    if mode == "oauth":
        tokens = garmin_ingest._ensure_fresh_tokens(db, user, token_row)  # pylint: disable=protected-access
    else:
        tokens = decrypt_user_tokens(token_row)
    access_token = tokens.get("access_token")
    token_secret = None
    meta = tokens.get("metadata") or {}
    if mode == "scraper":
        token_secret = meta.get("token_secret") or tokens.get("refresh_token")
    else:
        token_secret = meta.get("token_secret")
    client = garmin_ingest._build_garth_client(access_token, token_secret)  # pylint: disable=protected-access
    target_date = None
    if date:
        try:
            target_date = datetime.fromisoformat(date).date()
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=400, detail="Invalid date format") from exc
    if category in STAT_FETCHERS:
        try:
            data = STAT_FETCHERS[category](client, target_date or datetime.utcnow().date(), 1)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "category": category,
            "provider": provider_key,
            "mode": mode,
            "date": target_date.isoformat() if target_date else None,
            "result_size": len(data) if isinstance(data, list) else 1,
            "data_sample": data[:1] if isinstance(data, list) else data,
        }
    mapping = CONNECTAPI_SOURCES.get(category)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Unknown category {category}")
    try:
        method = (method_override or mapping.get("method") or "GET").upper()
        path_template = path_override or mapping.get("path")
        params_template = params_override or mapping.get("params")
        if mapping.get("per_day", False):
            target_date = target_date or datetime.utcnow().date()
            path = path_template.format(date=target_date.strftime("%Y-%m-%d"))
            params = None
            if isinstance(params_template, dict):
                params = {
                    k: (v.format(date=target_date.strftime("%Y-%m-%d")) if isinstance(v, str) else v)
                    for k, v in params_template.items()
                }
            data = client.connectapi(path, method=method, params=params)
        else:
            start_dt = datetime.fromisoformat(start_date_override).date() if start_date_override else datetime.utcnow().date()
            end_dt = datetime.fromisoformat(end_date_override).date() if end_date_override else datetime.utcnow().date()
            path = path_template.format(start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"))
            params = params_override
            data = client.connectapi(path, method=method, params=params)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "category": category,
        "provider": provider_key,
        "mode": mode,
        "date": target_date.isoformat() if target_date else None,
        "result_size": len(data) if isinstance(data, list) else 1,
        "data_sample": data[:1] if isinstance(data, list) else data,
    }


@router.get("/test-data/summary")
def summarize_test_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Summarize Postgres and Influx rows tied to TEST_ ingest runs for this user."""
    try:
        test_runs = (
            db.query(IngestRun)
            .filter(
                IngestRun.user_id == user.id,
                IngestRun.summary["test_run"].as_boolean() == True,  # pylint: disable=singleton-comparison
            )
            .all()
        )
    except Exception:
        test_runs = []
    run_ids = [r.id for r in test_runs]
    run_ids_str = [str(rid) for rid in run_ids]
    activity_count = (
        db.query(func.count(Activity.id))
        .filter(Activity.user_id == user.id, Activity.ingest_run_id.in_(run_ids))
        .scalar()
        if run_ids
        else 0
    )
    decision_count = (
        db.query(func.count(IngestDecision.id))
        .filter(IngestDecision.user_id == user.id, IngestDecision.ingest_run_id.in_(run_ids))
        .scalar()
        if run_ids
        else 0
    )

    influx_counts = []
    try:
        if run_ids:
            client = get_influx_client_for_user(db, user.id)
            tags = [f"TEST_{rid}" for rid in run_ids_str]
            pattern = "|".join([t.replace("-", r"\-") for t in tags])
            predicate = f'r.ingest_run_id =~ /^({pattern})$/'
            flux = f'''
from(bucket: "{client.default_bucket}")
  |> range(start: 0)
  |> filter(fn: (r) => {predicate})
  |> group(columns: ["_measurement"])
  |> count()
  |> group()
'''
            tables = client.query_api().query(org=client.org, query=flux)
            for table in tables:
                for record in table.records:
                    influx_counts.append(
                        {
                            "measurement": record.get_measurement(),
                            "count": record.get_value(),
                        }
                    )
    except Exception as exc:  # pylint: disable=broad-except
        # Flux may be disabled on Influx 1.x; attempt InfluxQL fallback.
        try:
            ds = get_user_datasource(db, user.id)
            if ds and ds.influx_url and ds.influx_bucket:
                token = decrypt_token(ds.token_encrypted)
                auth = None
                headers = {}
                if ds.influx_user and token:
                    auth = (ds.influx_user, token)
                elif token:
                    headers["Authorization"] = f"Token {token}"
                meas_resp = requests.get(
                    f"{ds.influx_url}/query",
                    params={"db": ds.influx_bucket, "q": "SHOW MEASUREMENTS"},
                    auth=auth,
                    headers=headers,
                    timeout=5,
                )
                if meas_resp.ok:
                    measurements = [
                        row[0] for row in meas_resp.json().get("results", [{}])[0].get("series", [{}])[0].get("values", [])
                    ]
                    for m in measurements:
                        q = f'SELECT COUNT(*) FROM "{m}" WHERE "ingest_run_id" =~ /^({pattern})$/'
                        cnt_resp = requests.get(
                            f"{ds.influx_url}/query",
                            params={"db": ds.influx_bucket, "q": q},
                            auth=auth,
                            headers=headers,
                            timeout=5,
                        )
                        if cnt_resp.ok:
                            res = cnt_resp.json().get("results", [{}])[0].get("series", [])
                            if res and "values" in res[0]:
                                vals = res[0]["values"][0]
                                # values layout: [time, count_field1, count_field2, ...]; sum counts
                                total = sum(v for v in vals[1:] if isinstance(v, (int, float)))
                                influx_counts.append({"measurement": m, "count": int(total)})
        except Exception as exc2:  # pylint: disable=broad-except
            logger.warning(
                "test data influx summary failed",
                extra={"user_id": str(user.id), "error": str(exc), "fallback_error": str(exc2)},
            )

    return {
        "test_runs": run_ids_str,
        "activities": activity_count,
        "ingest_decisions": decision_count,
        "influx": influx_counts,
    }


@router.post("/test-data/clear")
def clear_test_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete Postgres + Influx data tied to TEST_ ingest runs for this user."""
    summary = summarize_test_data(user=user, db=db)
    run_ids_str = summary.get("test_runs") or []
    run_ids = [UUID(rid) for rid in run_ids_str]

    # Postgres deletes
    if run_ids:
        db.query(Activity).filter(Activity.user_id == user.id, Activity.ingest_run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.query(IngestDecision).filter(
            IngestDecision.user_id == user.id, IngestDecision.ingest_run_id.in_(run_ids)
        ).delete(synchronize_session=False)
        db.query(IngestRun).filter(IngestRun.user_id == user.id, IngestRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.commit()
    # Also clean any lingering activities flagged as test_run in metadata (in case ingest_run was missing)
    try:
        db.query(Activity).filter(
            Activity.user_id == user.id, Activity.metadata["test_run"].as_boolean() == True  # pylint: disable=singleton-comparison
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "test data activity cleanup failed",
            extra={"user_id": str(user.id), "error": str(exc)},
        )

    # Influx deletes
    try:
        if run_ids:
            client = get_influx_client_for_user(db, user.id)
            tags = [f"TEST_{rid}" for rid in run_ids_str]
            pattern = "|".join([t.replace("-", r"\-") for t in tags])
            predicate = f'ingest_run_id=~/^({pattern})$/'
            delete_api = client.delete_api()
            delete_api.delete(
                start="1970-01-01T00:00:00Z",
                stop="2100-01-01T00:00:00Z",
                predicate=predicate,
                bucket=client.default_bucket,
                org=client.org,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("test data influx clear failed", extra={"user_id": str(user.id), "error": str(exc)})

    return {"status": "ok", "cleared_runs": run_ids_str}
