"""Guided onboarding routes for the post-auth /welcome flow."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Activity, ArchiveImportJob, AthleteGoal, SyncJob
from app.services.activity_summary import build_canonical_summary
from app.services.activity_quality import valid_distance_m
from app.services.providers import get_user_provider_token
from app.services.today_plan import GOAL_LABELS, PHASE_LABELS, save_goal
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
    """Minimal but evolvable athlete intent captured during activation."""

    goal: str = Field(min_length=1, max_length=32)
    phase: str = Field(default="build", min_length=1, max_length=32)
    target_date: date | None = None
    target_distance: str | None = Field(default=None, max_length=80)
    target_performance: str | None = Field(default=None, max_length=120)
    target_time_seconds: int | None = Field(default=None, gt=0, le=172800)
    custom_goal: str | None = Field(default=None, max_length=240)


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


def _selected_goal(
    persisted_goal: AthleteGoal | None,
    job: SyncJob | None,
    request: Request,
) -> str | None:
    """Resolve intent from durable athlete state before legacy onboarding hints."""
    if persisted_goal is not None:
        return persisted_goal.goal_type
    if job and isinstance(job.payload_json, dict):
        goal = job.payload_json.get("goal")
        if isinstance(goal, str) and goal:
            return goal
    return request.cookies.get(GOAL_COOKIE)


def _persisted_goal(db: Session, user: CurrentUserLike) -> AthleteGoal | None:
    """Return the athlete's durable goal/intent record."""
    return (
        db.query(AthleteGoal)
        .filter(AthleteGoal.user_id == user.id)
        .order_by(AthleteGoal.updated_at.desc())
        .first()
    )


def _latest_sync_job(db: Session, user: CurrentUserLike) -> SyncJob | None:
    """Return the most recent Garmin sync job for the user."""
    return (
        db.query(SyncJob)
        .filter(SyncJob.user_id == user.id, SyncJob.provider == "garmin")
        .order_by(SyncJob.created_at.desc())
        .first()
    )


def _latest_archive_job(
    db: Session, user: CurrentUserLike
) -> ArchiveImportJob | None:
    """Return persisted archive progress so activation survives navigation."""
    return (
        db.query(ArchiveImportJob)
        .filter(ArchiveImportJob.user_id == user.id)
        .order_by(ArchiveImportJob.created_at.desc())
        .first()
    )


def _intent_payload(
    goal: AthleteGoal | None,
    fallback_goal: str | None = None,
) -> dict | None:
    """Serialize athlete intent without exposing persistence details."""
    if goal is None:
        if not fallback_goal:
            return None
        return {
            "goal_type": fallback_goal,
            "label": GOAL_LABELS.get(
                fallback_goal, fallback_goal.replace("_", " ").title()
            ),
            "phase": None,
            "phase_label": None,
            "target_date": None,
            "target_distance": None,
            "target_performance": None,
            "target_time_seconds": None,
            "custom_goal": None,
        }

    details = dict(goal.intent_json or {})
    label = GOAL_LABELS.get(
        goal.goal_type, goal.goal_type.replace("_", " ").title()
    )
    if goal.goal_type == "other" and details.get("custom_goal"):
        label = str(details["custom_goal"])
    return {
        "goal_type": goal.goal_type,
        "label": label,
        "phase": goal.phase,
        "phase_label": PHASE_LABELS.get(
            goal.phase, goal.phase.replace("_", " ").title()
        ),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "target_distance": details.get("target_distance"),
        "target_performance": details.get("target_performance"),
        "target_time_seconds": details.get("target_time_seconds"),
        "custom_goal": details.get("custom_goal"),
    }


def _latest_activity_time(activities: list[dict]) -> datetime | None:
    if not activities:
        return None
    raw = activities[0].get("start_time")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _activation_state(
    *,
    garmin_token,
    garmin_connected: bool,
    garmin_authorization_available: bool,
    garmin_sync_available: bool,
    sync_job: SyncJob | None,
    archive_job: ArchiveImportJob | None,
    activities: list[dict],
    intent: dict | None,
    now: datetime,
) -> dict:
    """Compose one athlete-facing activation contract from existing durable truth."""
    usable_now = bool(activities)
    latest_activity = _latest_activity_time(activities)
    stale = bool(
        latest_activity is not None and now - latest_activity > FRESHNESS_WINDOW
    )
    sync_status = getattr(sync_job, "status", None)
    archive_status = getattr(archive_job, "status", None)
    sync_active = sync_status in {"queued", "running"}
    archive_active = archive_status in {
        "upload_pending",
        "uploaded",
        "queued",
        "processing",
        "running",
    }
    authorization_failed = (
        sync_status == "failed" and _failure_category(sync_job) == "authorization"
    )
    authorization_expired = garmin_token is not None and not garmin_connected
    import_failed = archive_status == "failed" or (
        sync_status == "failed" and not authorization_failed
    )

    if sync_active or archive_active:
        state = "usable_partial" if usable_now else "importing"
    elif authorization_expired or authorization_failed:
        state = "authorization_expired"
    elif import_failed:
        state = "import_failed"
    elif usable_now and stale:
        state = "stale"
    elif usable_now:
        state = "fully_usable"
    elif garmin_connected and not garmin_sync_available:
        state = "unsupported_capability"
    elif garmin_connected:
        state = "connected_no_data"
    else:
        state = "not_connected"

    if state in {"importing", "usable_partial"}:
        action = {
            "kind": "wait",
            "label": "Import in progress",
            "href": "/training",
            "enabled": False,
        }
    elif state == "authorization_expired":
        action = (
            {
                "kind": "reconnect",
                "label": "Reconnect training source",
                "href": "/api/providers/garmin/login?next=/settings",
                "enabled": True,
            }
            if garmin_authorization_available
            else {
                "kind": "archive",
                "label": "Review training data options",
                "href": "/import/garmin-archive",
                "enabled": True,
            }
        )
    elif state == "import_failed":
        action = {
            "kind": "archive",
            "label": "Review import and try again",
            "href": "/import/garmin-archive",
            "enabled": True,
        }
    elif state == "unsupported_capability":
        action = {
            "kind": "archive",
            "label": "Use a supported training import",
            "href": "/import/garmin-archive",
            "enabled": True,
        }
    elif state in {"connected_no_data", "stale", "fully_usable"} and garmin_connected and garmin_sync_available:
        action = {
            "kind": "refresh" if usable_now else "sync",
            "label": "Refresh training data" if usable_now else "Import recent training",
            "href": None,
            "enabled": True,
        }
    else:
        action = {
            "kind": "archive",
            "label": "Review training data options",
            "href": "/import/garmin-archive",
            "enabled": True,
        }

    messages = {
        "not_connected": "Add training history when you are ready; your goal can be refined at any time.",
        "connected_no_data": "Your training source is ready, but no usable activities have arrived yet.",
        "importing": "Training history is loading. You can keep exploring while it runs.",
        "usable_partial": "Some training history is already usable while more data continues loading.",
        "fully_usable": "Fitness Pals already has enough training history to start helping.",
        "stale": "Your saved training history is usable, but the newest activity is older than expected.",
        "authorization_expired": "Future updates need your attention; saved training history remains available.",
        "import_failed": "The latest import did not finish. Existing saved training history is unchanged.",
        "unsupported_capability": "That connection cannot import activities here yet. A supported archive path is available.",
    }
    intent_label = (intent or {}).get("label") or "your current goal"
    prompt = (
        f"Using the training data you have so far, help me turn {intent_label} "
        "into the most useful next step. Call out any important data limitations."
    )
    coach_href = (
        "/coach?from=%2Fwelcome&prompt=" + quote(prompt, safe="")
    )
    return {
        "state": state,
        "requires_activation": not usable_now,
        "usable_now": usable_now,
        "resume_href": "/today" if usable_now else "/welcome",
        "message": messages[state],
        "action": action,
        "background": {
            "sync": sync_status,
            "archive_import": archive_status,
        },
        "intent": intent,
        "coach_handoff": {
            "href": coach_href,
            "label": "Continue with Coach",
        },
    }


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
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist athlete intent in the same durable goal used by Today and Coach."""
    if body.goal not in GOAL_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported goal type")
    if body.phase not in PHASE_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported training phase")

    details = {
        "target_distance": body.target_distance,
        "target_performance": body.target_performance,
        "target_time_seconds": body.target_time_seconds,
        "custom_goal": body.custom_goal,
    }
    save_goal(
        db,
        user.id,
        goal_type=body.goal,
        phase=body.phase,
        target_date=body.target_date,
        intent_json=details,
        intent_source="onboarding",
    )
    persisted = _persisted_goal(db, user)
    _set_goal_cookie(response, body.goal)
    return {
        "goal": body.goal,
        "intent": _intent_payload(persisted, body.goal),
    }


@router.get("/status")
def status(
    request: Request,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one durable, athlete-facing activation and first-value state."""
    provider_key = _garmin_provider_key()
    garmin_token = get_user_provider_token(
        db,
        user.id,
        provider_key,
        getattr(user, "tenant_id", None),
    )
    now = datetime.now(timezone.utc)
    garmin_connected = _garmin_token_active(garmin_token, now)
    latest_job = _latest_sync_job(db, user)
    latest_archive_job = _latest_archive_job(db, user)
    persisted_goal = _persisted_goal(db, user)
    selected_goal = _selected_goal(persisted_goal, latest_job, request)
    intent = _intent_payload(persisted_goal, selected_goal)
    latest_activities = _latest_activities(db, user)

    first_sync_state, failure_category = _first_sync_state(
        garmin_connected or bool(latest_activities),
        latest_job,
        latest_activities,
        now,
    )

    preview = (
        _training_volume_preview(db, user, selected_goal)
        if latest_activities
        else None
    )
    coach_insight = (
        _coach_insight(db, user, selected_goal) if latest_activities else None
    )
    next_action = (
        _next_action(db, user, selected_goal) if latest_activities else None
    )
    garmin_authorization_available = (
        (os.environ.get("GARMIN_MODE") or "scraper").lower() == "oauth"
        and all(
            os.environ.get(key)
            for key in (
                "GARMIN_CLIENT_ID",
                "GARMIN_CLIENT_SECRET",
                "GARMIN_REDIRECT_URI",
            )
        )
    )
    garmin_sync_available = not (
        garmin_token is not None
        and (garmin_token.metadata_json or {}).get("auth_scheme")
        == "garmin_official_oauth2"
    )
    activation = _activation_state(
        garmin_token=garmin_token,
        garmin_connected=garmin_connected,
        garmin_authorization_available=garmin_authorization_available,
        garmin_sync_available=garmin_sync_available,
        sync_job=latest_job,
        archive_job=latest_archive_job,
        activities=latest_activities,
        intent=intent,
        now=now,
    )

    return {
        "authenticated": True,
        "garmin_connected": garmin_connected,
        "garmin_authorization_available": garmin_authorization_available,
        "garmin_sync_available": garmin_sync_available,
        "selected_goal": selected_goal,
        "intent": intent,
        "activation": activation,
        "first_sync": {
            "state": first_sync_state,
            "last_synced_at": (
                latest_activities[0]["start_time"] if latest_activities else None
            ),
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
