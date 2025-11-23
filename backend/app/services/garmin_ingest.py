"""Minimal Garmin ingestion helper using stored OAuth tokens."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
import uuid
from typing import Optional

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session
import garth
from types import SimpleNamespace

from app.models import IngestRun, Activity
from app.services import dedupe
from app.services.influx import get_influx_client_for_user
from app.services.garmin_fetchers import fetch_and_write_categories
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.routes import providers_garmin


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


def _build_garth_client(access_token: str, token_secret: Optional[str] = None) -> garth.Client:
    client = garth.Client()
    client.oauth1_token = SimpleNamespace(
        oauth_token=access_token,
        oauth_token_secret=token_secret or "",
        mfa_token=None,
        mfa_expiration_timestamp=None,
        domain="garmin.com",
    )
    return client


def _write_influx_points(db: Session, user, run: IngestRun, activities: list[dict]):
    """Write a minimal summary of activities to Influx with user/ingest tags."""
    try:
        client = get_influx_client_for_user(db, user.id)
    except Exception:
        # If no Influx datasource is configured, skip silently.
        return
    if not activities:
        return
    # InfluxDBClient v3 API: use write_api with point dicts (line protocol via dicts)
    write_api = client.write_api()
    points = []
    for item in activities:
        fields = {}
        # Minimal fields: distance, duration, avg_hr if present
        if "distance" in item:
            fields["distance"] = float(item.get("distance") or 0.0)
        if "duration" in item:
            fields["duration"] = float(item.get("duration") or 0.0)
        if "averageHR" in item:
            fields["average_hr"] = float(item.get("averageHR") or 0.0)
        if not fields:
            continue
        point = {
            "measurement": "ActivitySummary",
            "tags": {
                "user_id": str(user.id),
                "ingest_run_id": str(run.id),
                "provider": "garmin",
            },
            "time": None,
            "fields": fields,
        }
        points.append(point)
    if points:
        write_api.write(bucket=client.default_bucket, org=client.org, record=points)


def _persist_activities(db: Session, user, run: IngestRun, activities: list[dict]) -> None:
    """Persist basic activity rows in Postgres with ingest linkage."""
    if not activities:
        return
    now = datetime.utcnow()
    created = []
    for item in activities:
        act_id = item.get("id") or item.get("activityId")
        if act_id is None:
            continue
        start_time = item.get("startTimeUTC") or item.get("startTimeGmt") or item.get("startTimeGMT")
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except Exception:
                start_time = None
        distance_m = None
        for key in ("distance", "distance_m", "totalDistance"):
            if key in item and item.get(key) is not None:
                try:
                    distance_m = float(item.get(key))
                except Exception:
                    distance_m = None
                break
        duration_s = None
        for key in ("duration", "elapsedDuration", "durationSeconds"):
            if key in item and item.get(key) is not None:
                try:
                    duration_s = float(item.get(key))
                except Exception:
                    duration_s = None
                break
        fingerprint = str(act_id)
        activity = Activity(
            id=uuid.uuid4(),
            user_id=user.id,
            ingest_run_id=run.id,
            start_time=start_time or now,
            duration_seconds=int(duration_s) if duration_s is not None else None,
            distance_m=distance_m,
            sport=item.get("activityName") or item.get("activityType") or None,
            status="completed",
            fingerprint_hash=fingerprint,
            metadata=item,
            created_at=now,
            updated_at=now,
        )
        created.append(activity)
        db.add(activity)
    if created:
        db.commit()


def fetch_garmin_recent(db: Session, user) -> IngestRun:
    """Fetch Garmin data and record ingest run summary."""
    mode = _mode()
    provider_key = "garmin" if mode == "oauth" else "garmin_scraper"
    token_row = get_user_provider_token(db, user.id, provider_key, getattr(user, "tenant_id", None))
    if not token_row:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    # Best-effort ensure datasource exists
    try:
        from app.services.influx import ensure_user_datasource
        ensure_user_datasource(db, user.id)
    except Exception:
        pass
    if mode == "oauth":
        tokens = _ensure_fresh_tokens(db, user, token_row)
    else:
        tokens = decrypt_user_tokens(token_row)
    # Preserve metadata for downstream lookups
    tokens["metadata"] = token_row.metadata_json or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    token_secret = None
    if mode == "scraper":
        meta_secret = tokens.get("metadata", {}).get("token_secret") if isinstance(tokens.get("metadata"), dict) else None
        token_secret = meta_secret or tokens.get("refresh_token")
    else:
        token_secret = tokens.get("metadata", {}).get("token_secret") if isinstance(tokens.get("metadata"), dict) else None
    client = _build_garth_client(access_token, token_secret)
    try:
        activities = client.connectapi(
            "activitylist-service/activities",
            params={"start": 0, "limit": 20},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=410, detail="Garmin reauth required") if mode == "scraper" else HTTPException(status_code=502, detail="Garmin fetch failed")
    run = dedupe.record_ingest_run(db, provider="garmin", user_id=getattr(user, "id", None))
    activity_list = activities if isinstance(activities, list) else []
    _write_influx_points(db, user, run, activity_list)
    _persist_activities(db, user, run, activity_list)
    # Fetch additional categories using garth and write to Influx
    cat_summary = fetch_and_write_categories(db, user, run, client)
    summary = {"fetched": len(activity_list)}
    if cat_summary:
        summary["categories"] = cat_summary
    dedupe.finish_ingest_run(db, run, status="completed", summary=summary)
    return run
