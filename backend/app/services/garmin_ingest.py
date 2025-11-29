"""Garmin ingestion orchestrator (tokens, client, delegation to domain modules)."""
# mypy: ignore-errors

from __future__ import annotations

import os
from datetime import datetime, timedelta
import logging
from typing import Optional

import garth
from fastapi import HTTPException
from sqlalchemy.orm import Session
from types import SimpleNamespace

from app.models import IngestRun
from app.services import dedupe
from app.services.influx import get_influx_client_for_user
from app.services.garmin_fetchers import fetch_health_bundle
from app.services.garmin_timeseries import build_timeseries, write_timeseries
from app.services.garmin_aggregates import build_aggregate_summary
from app.services.garmin import sleep as sleep_svc
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_user_tokens,
    get_user_provider_token,
    save_user_provider_token,
)
from app.services.garmin import activity as activity_svc
from app.routes import providers_garmin
from app.models.sleep import SleepSession


logger = logging.getLogger("garmin_ingest")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
logger.propagate = True


def _mode() -> str:
    return (os.environ.get("GARMIN_MODE") or "oauth").lower()


def _redact_token(token: Optional[str]) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _ensure_fresh_tokens(db: Session, user, token_row) -> dict:
    tokens = decrypt_user_tokens(token_row)
    expires_at: Optional[datetime] = tokens.get("expires_at")
    logger.info(
        "garmin token check",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "provider": getattr(token_row, "provider", None),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    if expires_at and expires_at > datetime.utcnow() + timedelta(minutes=5):
        return tokens
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    logger.info(
        "refreshing garmin token",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "refresh_token_hint": _redact_token(refresh_token),
        },
    )
    refreshed = providers_garmin._refresh_tokens(refresh_token)  # pylint: disable=protected-access
    if not refreshed:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    access_token, new_refresh, new_expires_at, payload = refreshed
    logger.info(
        "garmin token refreshed",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "new_access_hint": _redact_token(access_token),
            "new_refresh_hint": _redact_token(new_refresh),
            "expires_at": new_expires_at.isoformat() if new_expires_at else None,
        },
    )
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
    logger.info(
        "building garth client",
        extra={
            "access_hint": _redact_token(access_token),
            "secret_present": bool(token_secret),
        },
    )
    client = garth.Client()
    client.oauth1_token = SimpleNamespace(
        oauth_token=access_token,
        oauth_token_secret=token_secret or "",
        mfa_token=None,
        mfa_expiration_timestamp=None,
        domain="garmin.com",
    )
    return client


def _ensure_provider_user_id(db: Session, token_row, client) -> Optional[str]:
    """Ensure provider_user_id is available; fetch profile if missing."""
    if token_row.provider_user_id:
        return token_row.provider_user_id
    try:
        profile = client.connectapi("user-service/user/profile")
        if isinstance(profile, list):
            profile_obj = profile[0] if profile else {}
        elif isinstance(profile, dict):
            profile_obj = profile
        else:
            profile_obj = {}
        pid = (
            profile_obj.get("userId")
            or profile_obj.get("displayName")
            or profile_obj.get("username")
            or profile_obj.get("id")
        )
        if pid:
            token_row.provider_user_id = str(pid)
            db.commit()
            db.refresh(token_row)
            logger.info(
                "garmin provider user id persisted",
                extra={"provider_user_id": token_row.provider_user_id},
            )
            return token_row.provider_user_id
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "garmin profile fetch for provider_user_id failed",
            extra={"error": str(exc)},
            exc_info=True,
        )
    return None


def _maybe_get_influx_client(db: Session, user):
    try:
        return get_influx_client_for_user(db, user.id)
    except Exception:
        return None


def _persist_sleep_sessions_from_bundle(
    db: Session,
    user,
    run: IngestRun,
    bundle: dict,
    provider_key: str,
    test_run: bool = False,
) -> int:
    """Persist daily sleep DTOs from the bundle into Postgres."""
    count = 0
    sleep_data = bundle.get("stats", {}).get("sleep_data")
    if not isinstance(sleep_data, list):
        return 0
    for day in sleep_data:
        if not isinstance(day, dict):
            continue
        dto = day.get("daily_sleep_dto") or {}
        cal = dto.get("calendar_date") or dto.get("calendarDate")
        if cal and "calendarDate" not in dto:
            dto["calendarDate"] = cal
        if not dto.get("id") or not cal:
            continue
        try:
            sleep_svc.persist_sleep_session(
                db,
                user.id,
                provider_key or "garmin",
                dto,
                getattr(run, "id", None),
                test_run=test_run,
            )
            count += 1
        except Exception as exc:  # pylint: disable=broad-except
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(
                "persist sleep session failed",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "provider": provider_key,
                    "calendar_date": cal,
                    "error": str(exc),
                    "test_run": test_run,
                },
                exc_info=True,
            )
    return count


def fetch_garmin_recent(db: Session, user, test_run: bool = False) -> IngestRun:
    mode = _mode()
    provider_key = "garmin" if mode == "oauth" else "garmin_scraper"
    token_row = get_user_provider_token(db, user.id, provider_key, getattr(user, "tenant_id", None))
    if not token_row:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    try:
        from app.services.influx import ensure_user_datasource
        ensure_user_datasource(db, user.id)
    except Exception:
        pass
    if mode == "oauth":
        tokens = _ensure_fresh_tokens(db, user, token_row)
    else:
        tokens = decrypt_user_tokens(token_row)
    tokens["metadata"] = token_row.metadata_json or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=410, detail="Garmin reauth required")
    logger.info(
        "garmin fetch starting",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "mode": mode,
            "provider": provider_key,
            "expires_at": tokens.get("expires_at").isoformat() if tokens.get("expires_at") else None,
            "access_token_hint": _redact_token(access_token),
            "test_run": test_run,
        },
    )
    token_secret = None
    if mode == "scraper":
        meta_secret = tokens.get("metadata", {}).get("token_secret") if isinstance(tokens.get("metadata"), dict) else None
        token_secret = meta_secret or tokens.get("refresh_token")
    else:
        token_secret = tokens.get("metadata", {}).get("token_secret") if isinstance(tokens.get("metadata"), dict) else None
    client = _build_garth_client(access_token, token_secret)
    provider_user_id = _ensure_provider_user_id(db, token_row, client)
    try:
        if provider_user_id:
            client.username = str(provider_user_id)
    except Exception:
        pass

    run = dedupe.record_ingest_run(db, provider="garmin", user_id=getattr(user, "id", None))
    ingest_run_tag = f"TEST_{run.id}" if test_run else str(run.id)
    influx_client = _maybe_get_influx_client(db, user)

    gps_written_total = 0

    def _ingest_activity_batch(act_list):
        nonlocal gps_written_total
        if not act_list:
            return
        logger.info(
            "ingest activity batch start",
            extra={"count": len(act_list), "test_run": test_run, "ingest_run_id": str(run.id)},
        )
        activity_svc.write_activity_summary_influx(db, user, run, influx_client, ingest_run_tag, act_list)
        activity_svc.persist_activity_summaries(db, user, run, act_list, test_run=test_run)
        for act in act_list:
            act_id = act.get("activityId") or act.get("id")
            act_name = act.get("activityName")
            start_time = act.get("startTimeGmt") or act.get("startTimeGMT") or act.get("startTimeUTC")
            if isinstance(start_time, str):
                try:
                    start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                except Exception:
                    start_time = None
            samples = activity_svc.extract_activity_timeseries(
                client,
                act_id,
                act_name,
                start_time,
                user,
                provider_key,
                test_run,
            )
            gps_written_total_local = activity_svc.write_activity_gps(influx_client, user, run, ingest_run_tag, act_id, samples)
            gps_written_total_local = gps_written_total_local or 0
            gps_written_total += gps_written_total_local
        logger.info(
            "ingest activity batch complete",
            extra={
                "count": len(act_list),
                "gps_written_total": gps_written_total,
                "test_run": test_run,
                "ingest_run_id": str(run.id),
            },
        )

    # Activities: summary + details (ActivityGPS via FIT or JSON)
    last_start = None if test_run else activity_svc.get_latest_activity_start_time(db, user)
    activities = activity_svc.fetch_activity_list(
        client,
        user,
        mode,
        provider_key,
        test_run,
        since_start_time=last_start,
    )
    # If provider_user_id is still missing, try to infer from activities (ownerId/userProfileId)
    if not provider_user_id:
        logger.info(
            "garmin provider user id missing; attempting inference from activities",
            extra={"activities_count": len(activities)},
        )
    # Always try to capture a provider_user_id from activity payloads
    for act in activities:
        candidate = act.get("ownerId") or act.get("userProfileId") or act.get("username")
        if not candidate:
            continue
        inferred = str(candidate)
        try:
            client.username = inferred
        except Exception:
            pass
        if token_row.provider_user_id != inferred:
            try:
                token_row.provider_user_id = inferred
                db.commit()
                db.refresh(token_row)
                provider_user_id = inferred
                logger.info(
                    "garmin provider user id inferred from activity",
                    extra={"provider_user_id": provider_user_id},
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "failed to persist inferred provider_user_id",
                    extra={"error": str(exc), "provider_user_id": inferred},
                    exc_info=True,
                )
        break
    if not provider_user_id and not token_row.provider_user_id:
        logger.warning(
            "garmin provider user id could not be inferred",
            extra={"activities_count": len(activities)},
        )
    else:
        logger.info(
            "garmin provider user id resolved",
            extra={"provider_user_id": provider_user_id or token_row.provider_user_id},
        )
    gps_written_total = 0
    _ingest_activity_batch(activities)

    # Health bundle (validated endpoints only)
    end_date = datetime.utcnow().date()
    bundle = fetch_health_bundle(client, end_date=end_date, days=7, include_extra_connectapi=False)
    # Fallback activities from bundle if direct fetch returns none
    if not activities:
        bundle_acts = bundle.get("connectapi", {}).get("multi_day", {}).get("activities")
        if isinstance(bundle_acts, dict) and bundle_acts.get("results"):
            activities = bundle_acts.get("results") or []
            logger.info("using bundle activities fallback", extra={"count": len(activities)})
        elif isinstance(bundle_acts, list):
            activities = bundle_acts
            logger.info("using bundle activities fallback", extra={"count": len(activities)})
        _ingest_activity_batch(activities)
    points_written = 0
    if influx_client:
        points = build_timeseries(bundle, user, run, ingest_run_tag)
        points_written = write_timeseries(influx_client, points)
        logger.info(
            "garmin health timeseries written",
            extra={"points": points_written, "provider": provider_key, "test_run": test_run},
        )
    sleep_daily_count = _persist_sleep_sessions_from_bundle(
        db, user, run, bundle, provider_key=provider_key, test_run=test_run
    )
    aggregate_summary = build_aggregate_summary(bundle)
    aggregate_summary.update(
        {
            "activities": len(activities),
            "activity_gps_written": gps_written_total,
            "timeseries_points": points_written,
            "sleep_daily": sleep_daily_count,
            "test_run": test_run,
        }
    )
    dedupe.finish_ingest_run(db, run, status="completed", summary=aggregate_summary)
    return run
