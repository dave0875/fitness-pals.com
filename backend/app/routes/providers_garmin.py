"""Garmin OAuth connect/callback endpoints (OAuth-only, no credentials)."""

from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Annotated, Any, Dict, Optional, cast
from uuid import UUID

import requests  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
import garth

from app.deps import get_current_user
from app.db import get_db
from app.models import Activity, IngestRun, IngestDecision
from pydantic import BaseModel
from app.types import CurrentUserLike
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.services.garmin_scheduler import fetch_all as fetch_all_users
from app.services import garmin_ingest
from app.services.sync_jobs import run_garmin_sync_job
from app.services.garmin_fetchers import CONNECTAPI_SOURCES, STAT_FETCHERS

router = APIRouter(prefix="/api/providers/garmin", tags=["garmin"])
logger = logging.getLogger("garmin.routes")
logger.setLevel(logging.INFO)
GARMIN_NEXT_COOKIE = "garmin_oauth_next"


def _user_uuid(user: CurrentUserLike) -> UUID:
    """Normalize user.id to a UUID for type-checking and logging."""
    return UUID(str(getattr(user, "id")))


def _redact_token(token: Optional[str]) -> str:
    """Return a short hint of a token without exposing full value."""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _safe_next_path(
    candidate: Optional[str], default: str = "/welcome?garmin=connected"
) -> str:
    """Allow only local absolute paths for Garmin post-connect redirects."""
    if not candidate:
        return default
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    return candidate

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
        client.oauth1_token = SimpleNamespace(  # type: ignore[assignment]
            oauth_token=access_token,
            oauth_token_secret=token_secret or "",
            mfa_token=None,
            mfa_expiration_timestamp=None,
            domain="garmin.com",
        )
        profile = client.connectapi("user-service/user/profile")
        profile_obj: Dict[str, Any] = {}
        if isinstance(profile, dict):
            profile_obj = profile
        elif isinstance(profile, list) and profile and isinstance(profile[0], dict):
            profile_obj = profile[0]
        provider_user_id = (
            profile_obj.get("userId")
            or profile_obj.get("displayName")
            or profile_obj.get("username")
            or profile_obj.get("id")
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
def garmin_login(
    request: Request,
    _: Annotated[Any, Depends(get_current_user)]
):
    """Redirect the authenticated user to Garmin OAuth."""
    cfg = _require_env()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scope"],
        "state": state,
    }
    prepped = requests.Request("GET", cfg["auth_url"], params=params).prepare()
    url = prepped.url
    if url is None:
        raise HTTPException(status_code=500, detail="Failed to build Garmin auth URL")
    resp = RedirectResponse(url)
    resp.set_cookie(
        "garmin_oauth_state",
        state,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    resp.set_cookie(
        GARMIN_NEXT_COOKIE,
        _safe_next_path(
            request.query_params.get("next"), "/welcome?garmin=connected"
        ),
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp


def _resolve_tenant(user: CurrentUserLike) -> Optional[UUID]:
    """Return a tenant id if the user model carries one; otherwise None."""
    return getattr(user, "tenant_id", None)


@router.get("/callback")
def garmin_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange Garmin auth code for tokens and persist them securely."""
    cfg = _require_env()
    if error:
        raise HTTPException(status_code=400, detail=f"Garmin auth failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    stored_state = None
    try:
        stored_state = request.cookies.get("garmin_oauth_state")
    except Exception:
        stored_state = None
    if not state or not stored_state or state != stored_state:
        raise HTTPException(status_code=400, detail="Invalid state for Garmin auth")

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
            user_id=_user_uuid(user),
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
    response = RedirectResponse(
        url=_safe_next_path(
            request.cookies.get(GARMIN_NEXT_COOKIE), "/welcome?garmin=connected"
        ),
        status_code=303,
    )
    response.delete_cookie("garmin_oauth_state", path="/")
    response.delete_cookie(GARMIN_NEXT_COOKIE, path="/")
    return response


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
def garmin_refresh(user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)):
    """Refresh Garmin tokens or signal reauth when refresh fails or missing."""
    _require_env()
    token = get_user_provider_token(db, _user_uuid(user), "garmin", getattr(user, "tenant_id", None))
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
            user_id=_user_uuid(user),
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
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
    test_run: bool = False,
):
    """Queue recent Garmin data for the current user."""
    try:
        execution = run_garmin_sync_job(
            db,
            user=user,
            trigger="manual",
            test_run=test_run,
        )
        return {
            "status": "queued",
            "sync_job_id": str(execution.job.id),
            "ingested": 0,
            "test_run": test_run,
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
def garmin_fetch_all(_: Annotated[Any, Depends(get_current_user)], db: Session = Depends(get_db)):
    """Fetch recent Garmin data for all users with Garmin tokens."""
    try:
        summary = fetch_all_users(db)
        return summary
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Garmin batch fetch failed") from exc


@router.get("/token-status")
def garmin_token_status(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
    provider: Optional[str] = None,
    include_all: bool = False,
):
    """Return metadata about the stored Garmin token for the current user."""
    tenant_id = _resolve_tenant(user)
    env_mode = (os.environ.get("GARMIN_MODE") or "oauth").lower()
    provider_key = provider or ("garmin" if env_mode == "oauth" else "garmin_scraper")
    user_uuid = _user_uuid(user)
    token = get_user_provider_token(db, user_uuid, provider_key, tenant_id)
    if include_all:
        other = "garmin_scraper" if provider_key == "garmin" else "garmin"
        tokens = [
            serialize_token_status(token, provider_key, user, tenant_id),
            serialize_token_status(
                get_user_provider_token(db, user_uuid, other, tenant_id), other, user, tenant_id
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


def serialize_token_status(token, provider_key: str, user: CurrentUserLike, tenant_id: Optional[UUID]):
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
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store a scraper access token (no username/password accepted)."""
    token_row = save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=_user_uuid(user),
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
    user: CurrentUserLike = Depends(get_current_user),
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
            user_id=_user_uuid(user),
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
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh the stored Garmin OAuth token when refresh_token is present."""
    tenant_id = _resolve_tenant(user)
    token_row = get_user_provider_token(db, _user_uuid(user), "garmin", tenant_id)
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
    expires_at_val = cast(Optional[datetime], token_row.expires_at)
    if isinstance(expires_in, (int, float)):
        expires_at_val = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    if not access_token:
        raise HTTPException(status_code=400, detail="Garmin refresh missing access token")
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=_user_uuid(user),
            tenant_id=tenant_id,
            provider="garmin",
            access_token=access_token,
            refresh_token=new_refresh,
            scope=payload.get("scope") or tokens.get("scope"),
            provider_user_id=cast(Optional[str], token_row.provider_user_id),
            expires_at=expires_at_val,
            metadata={"token_received_at": datetime.utcnow().isoformat()},
        ),
    )
    return {
        "status": "ok",
        "expires_at": expires_at_val.isoformat() if expires_at_val else None,
        "refresh_token_present": True,
    }


@router.get("/categories")
def list_garmin_categories(_: Annotated[Any, Depends(get_current_user)]):
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
    user: CurrentUserLike = Depends(get_current_user),
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
    token_row = get_user_provider_token(db, _user_uuid(user), provider_key, getattr(user, "tenant_id", None))
    if not token_row:
        raise HTTPException(status_code=410, detail="Garmin token missing for probe")
    if mode == "oauth":
        tokens = garmin_ingest._ensure_fresh_tokens(db, user, token_row)  # pylint: disable=protected-access
    else:
        tokens = decrypt_user_tokens(token_row)
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=410, detail="Garmin token missing")
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
        if isinstance(data, list):
            data_sample = data[:1]
            result_size = len(data)
        else:
            data_sample = data
            result_size = 1
        return {
            "category": category,
            "provider": provider_key,
            "mode": mode,
            "date": target_date.isoformat() if target_date else None,
            "result_size": result_size,
            "data_sample": data_sample,
        }
    mapping = CONNECTAPI_SOURCES.get(category)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Unknown category {category}")
    try:
        method = (method_override or mapping.get("method") or "GET").upper()
        path_template = path_override or mapping.get("path")
        if not path_template:
            raise HTTPException(status_code=400, detail="Category path missing")
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
    connectapi_sample: Any
    if isinstance(data, list):
        data_list = cast(list[Any], data)
        result_size = len(data_list)
        connectapi_sample = data_list[:1]
    else:
        result_size = 1
        connectapi_sample = data
    return {
        "category": category,
        "provider": provider_key,
        "mode": mode,
        "date": target_date.isoformat() if target_date else None,
        "result_size": result_size,
        "data_sample": connectapi_sample,
    }


@router.get("/test-data/summary")
def summarize_test_data(user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)):
    """Summarize canonical rows tied to TEST_ ingest runs for this user."""
    try:
        user_uuid = _user_uuid(user)
        test_runs = (
            db.query(IngestRun)
            .filter(
                IngestRun.user_id == user_uuid,
                IngestRun.summary["test_run"].as_boolean(),
            )
            .all()
        )
    except Exception:
        test_runs = []
    run_ids = [r.id for r in test_runs]
    run_ids_str = [str(rid) for rid in run_ids]
    activity_count = 0
    decision_count = 0
    if run_ids:
        activity_count = (
            db.query(func.count(Activity.id))
            .filter(Activity.user_id == _user_uuid(user), Activity.ingest_run_id.in_(run_ids))
            .scalar()
            or 0
        )
        decision_count = (
            db.query(func.count(IngestDecision.id))
            .filter(IngestDecision.user_id == _user_uuid(user), IngestDecision.ingest_run_id.in_(run_ids))
            .scalar()
            or 0
        )

    return {
        "test_runs": run_ids_str,
        "activities": activity_count,
        "ingest_decisions": decision_count,
    }


@router.post("/test-data/clear")
def clear_test_data(user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete canonical data tied to TEST_ ingest runs for this user."""
    summary = summarize_test_data(user=user, db=db)
    run_ids_str = summary.get("test_runs") or []
    run_ids = [UUID(rid) for rid in run_ids_str]

    # Postgres deletes
    if run_ids:
        db.query(Activity).filter(Activity.user_id == _user_uuid(user), Activity.ingest_run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.query(IngestDecision).filter(
            IngestDecision.user_id == _user_uuid(user), IngestDecision.ingest_run_id.in_(run_ids)
        ).delete(synchronize_session=False)
        db.query(IngestRun).filter(IngestRun.user_id == _user_uuid(user), IngestRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.commit()
    # Also clean any lingering activities flagged as test_run in metadata (in case ingest_run was missing)
    try:
        db.query(Activity).filter(
            Activity.user_id == _user_uuid(user), Activity.metadata_json["test_run"].as_boolean()
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "test data activity cleanup failed",
            extra={"user_id": str(user.id), "error": str(exc)},
        )

    return {"status": "ok", "cleared_runs": run_ids_str}
