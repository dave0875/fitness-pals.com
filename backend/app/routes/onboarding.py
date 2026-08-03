"""Guided onboarding routes for the post-auth /welcome flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Activity, SyncJob
from app.services.activity_summary import build_canonical_summary
from app.services.providers import get_user_provider_token
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
settings = get_settings()
GOAL_COOKIE = "runtrainer_goal_handshake"


class GoalHandshakeRequest(BaseModel):
    """Goal selection captured during first-run onboarding."""

    goal: str


class FirstSyncRequest(BaseModel):
    """Payload used to queue the user's first PulsAI sync."""

    goal: str



def _enqueue_pulsai_sync_job(
    db: Session, user: CurrentUserLike, goal: str
) -> SyncJob:
    """Queue PulsAI work lazily to avoid provider-service import cycles."""
    from app.services.sync_jobs import enqueue_sync_job

    return enqueue_sync_job(
        db,
        user_id=user.id,
        provider="pulsai",
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
    """Return the most recent PulsAI sync job for the user."""
    return (
        db.query(SyncJob)
        .filter(SyncJob.user_id == user.id, SyncJob.provider == "pulsai")
        .order_by(SyncJob.created_at.desc())
        .first()
    )


def _latest_activities(db: Session, user: CurrentUserLike, limit: int = 5) -> list[dict]:
    """Return the newest canonical activities for preview on /welcome."""
    activities = (
        db.query(Activity)
        .filter(Activity.user_id == user.id)
        .order_by(Activity.start_time.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(activity.id),
            "sport": activity.sport,
            "start_time": activity.start_time.isoformat(),
            "distance_m": float(activity.distance_m or 0),
            "duration_seconds": activity.duration_seconds,
        }
        for activity in activities
    ]


def _readiness_preview(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return a small first-win readiness preview from canonical activity data."""
    summary = build_canonical_summary(db, user.id)
    mileage_30 = float(summary["mileage"]["30d"] or 0.0) / 1609.34
    longest_run = float(summary["long_run_max"] or 0.0) / 1609.34
    if mileage_30 <= 0 and longest_run <= 0:
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

    return {
        "score": score,
        "label": label,
        "summary": (
            f"{goal_prefix}: {mileage_30:.1f} miles in the last 30 days, "
            f"with a longest recent run of {longest_run:.1f} miles."
        ),
    }


def _coach_insight(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return a concise first-win coaching insight grounded in recent activity."""
    summary = build_canonical_summary(db, user.id)
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
                f"You have {mileage_30:.1f} miles in the last 30 days and a recent long run of "
                f"{longest_run:.1f} miles. The smart play now is to protect consistency while the "
                "system learns how your load and recovery behave together."
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
            f"{longest_run:.1f}-mile long run. That is enough signal for the product to start adjusting "
            "guidance instead of offering generic coaching."
        ),
    }


def _next_action(db: Session, user: CurrentUserLike, goal: str | None) -> dict | None:
    """Return the next best onboarding action after first sync completes."""
    summary = build_canonical_summary(db, user.id)
    mileage_30 = float(summary["mileage"]["30d"] or 0.0) / 1609.34
    longest_run = float(summary["long_run_max"] or 0.0) / 1609.34
    if mileage_30 <= 0 and longest_run <= 0:
        return None

    normalized_goal = (goal or "").lower()
    if normalized_goal == "marathon":
        return {
            "label": "Open your dashboard and protect the next easy day",
            "description": (
                "Do not spend this first sync looking for hero workouts. Let the product map your pattern, "
                "then keep the next run conversational so consistency remains intact."
            ),
            "href": "/dashboard",
        }
    if normalized_goal == "consistency":
        return {
            "label": "Use the dashboard to plan two calm runs",
            "description": (
                "The fastest way to create better guidance is to give the system two more ordinary training days, "
                "not one perfect one."
            ),
            "href": "/dashboard",
        }
    return {
        "label": "Open the dashboard and review your latest readiness",
        "description": (
            "Start with the latest readiness view, then decide whether the next session should build load "
            "or preserve recovery."
        ),
        "href": "/dashboard",
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
    pulsai_connected = (
        get_user_provider_token(
            db,
            user.id,
            "pulsai",
            getattr(user, "tenant_id", None),
        )
        is not None
    )
    latest_job = _latest_sync_job(db, user)
    selected_goal = _selected_goal(latest_job, request)
    latest_activities = _latest_activities(db, user)

    if not pulsai_connected:
        first_sync_state = "not_started"
    elif latest_activities:
        first_sync_state = "completed"
    elif latest_job and latest_job.status in {"queued", "running"}:
        first_sync_state = latest_job.status
    else:
        first_sync_state = "not_started"

    preview = _readiness_preview(db, user, selected_goal) if latest_activities else None
    coach_insight = _coach_insight(db, user, selected_goal) if latest_activities else None
    next_action = _next_action(db, user, selected_goal) if latest_activities else None

    return {
        "authenticated": True,
        "pulsai_connected": pulsai_connected,
        "selected_goal": selected_goal,
        "first_sync": {
            "state": first_sync_state,
            "last_synced_at": latest_activities[0]["start_time"] if latest_activities else None,
            "sync_job_id": str(latest_job.id) if latest_job else None,
        },
        "latest_activities": latest_activities,
        "readiness_preview": preview,
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
    """Queue a first PulsAI sync and persist the selected goal to the job payload."""
    pulsai_token = get_user_provider_token(
        db,
        user.id,
        "pulsai",
        getattr(user, "tenant_id", None),
    )
    if pulsai_token is None:
        raise HTTPException(status_code=409, detail="PulsAI must be connected first")

    job = _enqueue_pulsai_sync_job(db, user, body.goal)
    _set_goal_cookie(response, body.goal)
    return {
        "state": "queued",
        "sync_job_id": str(job.id),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
