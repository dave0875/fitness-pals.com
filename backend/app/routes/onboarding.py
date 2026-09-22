"""Guided onboarding routes for the post-auth /welcome flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Activity, SyncJob
from app.services.activity_summary import build_canonical_summary
from app.services.activity_quality import valid_distance_m
from app.services.providers import get_user_provider_token
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
settings = get_settings()
GOAL_COOKIE = "runtrainer_goal_handshake"
FRESHNESS_WINDOW = timedelta(hours=72)


def _garmin_provider_key() -> str:
    """Return the credential key used by the configured Garmin integration."""
    return (
        "garmin"
        if (os.environ.get("GARMIN_MODE") or "scraper").lower() == "oauth"
        else "garmin_scraper"
    )


def _garmin_token_active(token, now: datetime | None = None) -> bool:
    """Treat an expired 30-day Garmin grant as disconnected."""
    if token is None:
        return False
    expires_at = getattr(token, "expires_at", None)
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > (now or datetime.now(timezone.utc))


class GoalHandshakeRequest(BaseModel):
    """Goal selection captured during first-run onboarding."""

    goal: str


class FirstSyncRequest(BaseModel):
    """Payload used to queue the user's first Garmin sync."""

    goal: str


def _enqueue_garmin_sync_job(
    db: Session, user: CurrentUserLike, goal: str
) -> SyncJob:
    """Queue Garmin work lazily to avoid provider-service import cycles."""
    from app.services.sync_jobs import enqueue_sync_job

    return enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="manual",
        test_run=False,
        payload={"goal": goal},
    )


def _set_goal_cookie(response: Response, goal: str) -> None:
    """Attach the selected goal to a response for later onboarding steps."""
    response.set_cookie(
        GOAL_COOKIE,
        goal,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )


def _selected_goal(job: SyncJob | None, request: Request) -> str | None:
    """Resolve the currently selected onboarding goal."""
    if job and isinstance(job.payload_json, dict):
        goal = job.payload_json.get("goal")
        if isinstance(goal, str) and goal:
            return goal
    return request.cookies.get(GOAL_COOKIE)


def _latest_sync_job(db: Session, user: CurrentUserLike) -> SyncJob | None:
    """Return the most recent Garmin sync job for the user."""
    return (
        db.query(SyncJob)
        .filter(SyncJob.user_id == user.id, SyncJob.provider == "garmin")
        .order_by(SyncJob.created_at.desc())
        .first()
    )


def _utc(value: datetime) -> datetime:
    """Normalize persisted datetimes before freshness comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _failure_category(job: SyncJob | None) -> str | None:
    """Reduce provider errors to a safe recovery category."""
    if job is None or not isinstance(job.error_json, dict):
        return None
    error = job.error_json
    status_code = str(error.get("status_code", ""))
    searchable = " ".join(
        str(error.get(key, "")) for key in ("type", "message")
    ).lower()
    if status_code in {"401", "403", "410"} or any(
        marker in searchable
        for marker in ("authorization", "unauthorized", "forbidden", "credential")
    ):
        return "authorization"
    return "upstream"


def _first_sync_state(
    connected: bool,
    job: SyncJob | None,
    activities: list[dict],
    now: datetime,
) -> tuple[str, str | None]:
    """Resolve a recoverable state without returning raw provider failures."""
    if not connected:
        return "not_started", None
    if job and job.status in {"queued", "running"}:
        return job.status, None
    if job and job.status == "failed":
        category = _failure_category(job)
        if category == "authorization":
            return "authorization_required", category
        return "failed", category
    if job and job.status == "completed":
        if not activities:
            return "partial", None
        if job.finished_at and now - _utc(job.finished_at) > FRESHNESS_WINDOW:
            return "stale", None
        return "completed", None
    if activities:
        return "completed", None
    return "not_started", None


def _latest_activities(db: Session, user: CurrentUserLike, limit: int = 5) -> list[dict]:
    """Return the newest canonical activities for preview on /welcome."""
    activities = (
        db.query(Activity)
        .filter(Activity.user_id == user.id, Activity.status != "conflict")
        .order_by(Activity.start_time.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(activity.id),
            "sport": activity.sport,
            "start_time": activity.start_time.isoformat(),
            "distance_m": valid_distance_m(activity.distance_m, activity.sport),
            "duration_seconds": activity.duration_seconds,
        }
        for activity in activities
    ]


def _training_volume_preview(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return a first-win running-volume preview, never a readiness estimate."""
    summary = build_canonical_summary(db, user.id)
    if summary["mileage"]["30d"] is None:
        return None
    mileage_30 = float(summary["mileage"]["30d"] or 0.0) / 1609.34
    longest_run = summary["long_run_max"]
    if mileage_30 <= 0 and longest_run is None:
        return None

    score = min(100, max(0, round((mileage_30 / 40.0) * 100)))
    if score >= 75:
        label = "Building well"
    elif score >= 40:
        label = "Building steadily"
    else:
        label = "Foundation in progress"

    goal_prefix = {
        "marathon": "Marathon build",
        "half": "Half-marathon build",
        "recovery": "Recovery build",
        "consistency": "Consistency build",
    }.get((goal or "").lower(), "Training build")

    run_clause = (
        f", with a longest run of {longest_run / 1609.34:.1f} miles in the last 90 days"
        if longest_run is not None else ""
    )
    return {
        "score": score,
        "label": label,
        "summary": (
            f"{goal_prefix}: {mileage_30:.1f} running miles in the last 30 days"
            f"{run_clause}. This is training volume, not a recovery-based readiness score."
        ),
    }


def _coach_insight(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return a concise first-win coaching insight grounded in recent activity."""
    summary = build_canonical_summary(db, user.id)
    if summary["mileage"]["30d"] is None:
        return None
    mileage_30 = float(summary["mileage"]["30d"] or 0.0) / 1609.34
    longest_run = float(summary["long_run_max"] or 0.0) / 1609.34
    avg_weekly = float(summary["average_weekly_mileage"] or 0.0) / 1609.34
    if mileage_30 <= 0 and longest_run <= 0:
        return None

    normalized_goal = (goal or "").lower()
    if normalized_goal == "marathon" and longest_run >= 10:
        return {
            "title": "Your endurance base is already visible",
            "explanation": (
                f"You have {mileage_30:.1f} running miles in the last 30 days and a longest run in the last 90 days of "
                f"{longest_run:.1f} miles. This describes training history, not recovery-based readiness."
            ),
        }
    if normalized_goal == "recovery":
        return {
            "title": "Recovery should shape the next step",
            "explanation": (
                f"Your recent workload is about {avg_weekly:.1f} miles per week. Use that as a floor, "
                "not a dare, while the product learns where easier days should interrupt accumulated load."
            ),
        }
    if mileage_30 < 20:
        return {
            "title": "Consistency is the next unlock",
            "explanation": (
                f"With {mileage_30:.1f} miles in the last 30 days, the biggest gain is not sharper workouts. "
                "It is stacking calm, repeatable training days the product can learn from."
            ),
        }
    return {
        "title": "Your recent load is enough to shape decisions",
        "explanation": (
            f"You are carrying about {mileage_30:.1f} miles over the last 30 days with a "
            f"{longest_run:.1f}-mile run in the last 90 days. Recovery and intensity remain unknown "
            "until their signals are current."
        ),
    }


def _next_action(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return the next best onboarding action after first sync completes."""
    summary = build_canonical_summary(db, user.id)
    if summary["mileage"]["30d"] is None:
        return None
    mileage_30 = float(summary["mileage"]["30d"] or 0.0) / 1609.34
    longest_run = float(summary["long_run_max"] or 0.0) / 1609.34
    if mileage_30 <= 0 and longest_run <= 0:
        return None

    normalized_goal = (goal or "").lower()
    if normalized_goal == "marathon":
        return {
            "label": "Open Today and protect the next easy day",
            "description": (
                "Do not spend this first sync looking for hero workouts. Let the product map your pattern, "
                "then keep the next run conversational so consistency remains intact."
            ),
            "href": "/today",
        }
    if normalized_goal == "consistency":
        return {
            "label": "Use Today to plan two calm runs",
            "description": (
                "The fastest way to create better guidance is to give the system two more ordinary training days, "
                "not one perfect one."
            ),
            "href": "/today",
        }
    return {
        "label": "Open Today and review training history",
        "description": (
            "Start with your training history; recovery-based readiness remains unavailable without current signals."
        ),
        "href": "/today",
    }


@router.post("/goal")
def store_goal_handshake(
    body: GoalHandshakeRequest,
    response: Response,
    _: CurrentUserLike = Depends(get_current_user),
):
    """Persist the selected onboarding goal via a backend-managed cookie."""
    _set_goal_cookie(response, body.goal)
    return {"goal": body.goal}


@router.get("/status")
def status(
    request: Request,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the welcome-flow onboarding state for the current user."""
    provider_key = _garmin_provider_key()
    garmin_token = get_user_provider_token(
        db,
        user.id,
        provider_key,
        getattr(user, "tenant_id", None),
    )
    garmin_connected = _garmin_token_active(garmin_token)
    latest_job = _latest_sync_job(db, user)
    selected_goal = _selected_goal(latest_job, request)
    latest_activities = _latest_activities(db, user)

    first_sync_state, failure_category = _first_sync_state(
        garmin_connected or bool(latest_activities),
        latest_job,
        latest_activities,
        datetime.now(timezone.utc),
    )

    preview = _training_volume_preview(db, user, selected_goal) if latest_activities else None
    coach_insight = _coach_insight(db, user, selected_goal) if latest_activities else None
    next_action = _next_action(db, user, selected_goal) if latest_activities else None

    return {
        "authenticated": True,
        "garmin_connected": garmin_connected,
        "garmin_authorization_available": (
            (os.environ.get("GARMIN_MODE") or "scraper").lower() == "oauth"
            and all(os.environ.get(key) for key in (
                "GARMIN_CLIENT_ID", "GARMIN_CLIENT_SECRET", "GARMIN_REDIRECT_URI"
            ))
        ),
        # The existing scheduled importer calls private Connect endpoints and cannot
        # consume tokens issued to a registered Garmin partner application.
        "garmin_sync_available": not (
            garmin_token is not None
            and (garmin_token.metadata_json or {}).get("auth_scheme") == "garmin_official_oauth2"
        ),
        "selected_goal": selected_goal,
        "first_sync": {
            "state": first_sync_state,
            "last_synced_at": latest_activities[0]["start_time"] if latest_activities else None,
            "sync_job_id": str(latest_job.id) if latest_job else None,
            "failure_category": failure_category,
            "retryable": first_sync_state in {"failed", "partial", "stale"},
        },
        "latest_activities": latest_activities,
        "training_volume_preview": preview,
        "coach_insight": coach_insight,
        "next_action": next_action,
    }


@router.post("/first-sync")
def first_sync(
    body: FirstSyncRequest,
    response: Response,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a first Garmin sync and persist the selected goal to the job payload."""
    provider_key = _garmin_provider_key()
    garmin_token = get_user_provider_token(
        db,
        user.id,
        provider_key,
        getattr(user, "tenant_id", None),
    )
    if garmin_token is None or not _garmin_token_active(garmin_token):
        raise HTTPException(status_code=409, detail="Garmin must be connected first")
    if (garmin_token.metadata_json or {}).get("auth_scheme") == "garmin_official_oauth2":
        raise HTTPException(
            status_code=503,
            detail="Official Garmin activity import is not yet configured. Import a Garmin archive instead.",
        )

    existing_job = _latest_sync_job(db, user)
    if existing_job and existing_job.status in {"queued", "running"}:
        _set_goal_cookie(response, body.goal)
        queued_at = existing_job.created_at or datetime.now(timezone.utc)
        return {
            "state": existing_job.status,
            "sync_job_id": str(existing_job.id),
            "queued_at": _utc(queued_at).isoformat(),
            "reused": True,
        }

    job = _enqueue_garmin_sync_job(db, user, body.goal)
    _set_goal_cookie(response, body.goal)
    return {
        "state": "queued",
        "sync_job_id": str(job.id),
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "reused": False,
    }
