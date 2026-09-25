"""Canonical athlete-home read model composed from user-owned records."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from app.models import (
    Activity,
    DossierArtifact,
    DossierJob,
    SyncCheckpoint,
)
from app.services.activity_quality import valid_distance_m
from app.services.athlete_state import build_athlete_state

METERS_PER_MILE = 1609.344


def _utc(value: datetime | date) -> datetime:
    """Normalize persisted dates and datetimes for freshness comparisons."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _goal(goal: str | None) -> dict[str, str] | None:
    """Translate onboarding goal keys into product language."""
    if not goal:
        return None
    labels = {
        "marathon": "Marathon",
        "half": "Half marathon",
        "recovery": "Recovery",
        "consistency": "Consistency",
    }
    normalized = goal.lower()
    return {"key": normalized, "label": labels.get(normalized, goal.replace("_", " ").title())}


def _activity_payload(activity: Activity) -> dict[str, Any]:
    """Return an athlete-facing activity summary without provider-shaped payloads."""
    metadata = activity.metadata_json if isinstance(activity.metadata_json, dict) else {}
    title = (
        metadata.get("name")
        or metadata.get("activityName")
        or (activity.sport or "Activity").replace("_", " ").title()
    )
    return {
        "id": str(activity.id),
        "title": title,
        "sport": activity.sport,
        "start_time": _utc(activity.start_time).isoformat(),
        "distance_m": valid_distance_m(activity.distance_m, activity.sport),
        "duration_seconds": activity.duration_seconds,
    }


def _trend(activities: list[Activity], now: datetime) -> dict[str, Any]:
    """Compare the latest seven training days with the preceding seven."""
    current_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)
    current_m = sum(
        valid_distance_m(activity.distance_m, activity.sport) or 0
        for activity in activities
        if _utc(activity.start_time) >= current_start
    )
    previous_m = sum(
        valid_distance_m(activity.distance_m, activity.sport) or 0
        for activity in activities
        if previous_start <= _utc(activity.start_time) < current_start
    )
    current_miles = round(current_m / METERS_PER_MILE, 1)
    previous_miles = round(previous_m / METERS_PER_MILE, 1)

    if current_m == 0 and previous_m == 0:
        state = "unknown"
        explanation = "Two complete weeks of activity history are needed for a trend."
    elif previous_m == 0:
        state = "baseline"
        explanation = f"This week establishes a {current_miles:.1f}-mile baseline."
    else:
        change_percent = round(((current_m - previous_m) / previous_m) * 100)
        if change_percent > 10:
            state = "up"
        elif change_percent < -10:
            state = "down"
        else:
            state = "steady"
        explanation = (
            f"{current_miles:.1f} miles this week versus {previous_miles:.1f} last week "
            f"({change_percent:+d}%)."
        )

    return {
        "state": state,
        "label": "Seven-day volume",
        "current_miles": current_miles,
        "previous_miles": previous_miles,
        "explanation": explanation,
    }


def _training_consistency(activities: list[Activity], now: datetime) -> dict[str, Any]:
    """Score observed training volume and active days, not physiological readiness."""
    recent = [
        activity
        for activity in activities
        if _utc(activity.start_time) >= now - timedelta(days=30)
    ]
    if not recent:
        return {
            "state": "unknown",
            "score": None,
            "label": "Training consistency unavailable",
            "explanation": "Recent activity history is needed before consistency can be estimated.",
        }

    known_distances = [
        distance
        for activity in recent
        if (distance := valid_distance_m(activity.distance_m, activity.sport)) is not None
    ]
    active_days = len({_utc(activity.start_time).date() for activity in recent})
    if not known_distances:
        return {
            "state": "unknown",
            "score": None,
            "label": "Training consistency unavailable",
            "explanation": f"{active_days} active days are recorded, but measured distance is unknown.",
        }
    mileage = sum(known_distances) / METERS_PER_MILE
    volume_component = min(mileage / 40.0, 1.0) * 55
    consistency_component = min(active_days / 12.0, 1.0) * 45
    score = round(volume_component + consistency_component)

    if score >= 75:
        label = "Building well"
    elif score >= 45:
        label = "Building steadily"
    else:
        label = "Foundation in progress"

    return {
        "state": "available",
        "score": score,
        "label": label,
        "explanation": (
            f"Based on {mileage:.1f} miles across {active_days} active "
            f"day{'s' if active_days != 1 else ''} in the last 30 days."
        ),
    }


def _coaching_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical decision into the existing athlete-home coaching card."""
    action = decision.get("action") if isinstance(decision, dict) else {}
    action = action if isinstance(action, dict) else {}
    rationale = decision.get("rationale") if isinstance(decision, dict) else []
    rationale = rationale if isinstance(rationale, list) else []
    explanation = next(
        (
            item.get("summary")
            for item in rationale
            if isinstance(item, dict) and isinstance(item.get("summary"), str)
        ),
        "Open the unified athlete decision for its evidence and uncertainty.",
    )
    return {
        "insight": action.get("label") or "Review the next athlete decision",
        "explanation": explanation,
        "next_action": {
            "label": action.get("label") or "Open Today",
            "href": action.get("href") or "/today#todays-run",
        },
    }


def _dossier(
    artifacts: list[DossierArtifact],
    jobs: list[DossierJob],
) -> dict[str, Any]:
    """Summarize the athlete's latest immutable dossier or active request."""
    active_jobs = [job for job in jobs if job.status in {"queued", "generating"}]
    active_jobs.sort(
        key=lambda job: job.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if active_jobs:
        job = active_jobs[0]
        state_label = "Queued" if job.status == "queued" else "Generating"
        return {
            "state": job.status,
            "title": f"{state_label}: your next coaching dossier",
            "summary": "Generation continues in the background and will remain visible in your library.",
            "data_through": None,
            "freshness": None,
            "action": {"label": "View generation status", "href": "/dossiers"},
        }

    artifacts.sort(key=lambda artifact: int(artifact.version), reverse=True)
    if artifacts:
        artifact = artifacts[0]
        content = artifact.content_json if isinstance(artifact.content_json, dict) else {}
        return {
            "state": "completed",
            "title": content.get("title") or f"Coaching dossier v{artifact.version}",
            "summary": content.get("summary") or "Your latest coaching dossier is ready.",
            "data_through": (
                artifact.data_through.isoformat() if artifact.data_through else None
            ),
            "freshness": content.get("freshness") or "unknown",
            "version": artifact.version,
            "action": {
                "label": "Open latest dossier",
                "href": f"/dossiers/{artifact.id}",
            },
        }

    recoverable_jobs = [
        job for job in jobs if job.status in {"insufficient_data", "failed"}
    ]
    recoverable_jobs.sort(
        key=lambda job: job.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if recoverable_jobs:
        job = recoverable_jobs[0]
        summary = (
            "The selected window does not yet contain enough canonical activity data."
            if job.status == "insufficient_data"
            else "The last generation attempt did not complete; your existing history is unchanged."
        )
        return {
            "state": job.status,
            "title": "Your dossier needs attention",
            "summary": summary,
            "data_through": None,
            "freshness": "unknown",
            "action": {"label": "Review and retry", "href": "/dossiers"},
        }

    return {
        "state": "not_generated",
        "title": "Your first coaching dossier",
        "summary": "Turn your recent training and recovery into a durable coaching narrative.",
        "data_through": None,
        "freshness": None,
        "action": {"label": "Generate your first dossier", "href": "/dossiers"},
    }


def build_athlete_home(
    db,
    user_id: UUID,
    *,
    goal: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose an athlete-owned home response from canonical records."""
    current_time = _utc(now or datetime.now(timezone.utc))
    activities = sorted(
        [
            activity
            for activity in db.query(Activity).all()
            if getattr(activity, "user_id", None) == user_id
            and getattr(activity, "status", None) != "conflict"
        ],
        key=lambda activity: _utc(activity.start_time),
        reverse=True,
    )
    athlete_state = build_athlete_state(db, user_id, now=current_time, days=14)
    latest_recovery = athlete_state.get("latest")
    recovery_date = None
    if isinstance(latest_recovery, dict) and latest_recovery.get("date"):
        recovery_date = date.fromisoformat(latest_recovery["date"])
    checkpoints = [
        checkpoint
        for checkpoint in db.query(SyncCheckpoint).all()
        if getattr(checkpoint, "user_id", None) == user_id
    ]
    dossier_artifacts = [
        artifact
        for artifact in db.query(DossierArtifact).all()
        if getattr(artifact, "user_id", None) == user_id
    ]
    dossier_jobs = [
        job
        for job in db.query(DossierJob).all()
        if getattr(job, "user_id", None) == user_id
    ]

    data_candidates = [
        *(_utc(activity.start_time) for activity in activities[:1]),
        *([_utc(recovery_date)] if recovery_date is not None else []),
        *(
            _utc(checkpoint.last_synced_at)
            for checkpoint in checkpoints
            if checkpoint.last_synced_at is not None
        ),
    ]
    data_through = max(data_candidates) if data_candidates else None

    missing = []
    if not activities:
        missing.append("activities")
    if athlete_state.get("state") in {"unknown", "error"}:
        missing.append("sleep")

    if data_through is None:
        freshness_state = "empty"
        freshness_label = "No synced fitness history"
    elif current_time - data_through > timedelta(hours=72):
        freshness_state = "stale"
        freshness_label = "Your data needs a refresh"
    elif missing:
        freshness_state = "partial"
        freshness_label = "Some signals are still unknown"
    else:
        freshness_state = "fresh"
        freshness_label = "Fitness data is current"

    activity_time = _utc(activities[0].start_time) if activities else None
    sleep_time = _utc(recovery_date) if recovery_date is not None else None
    intensity_activity = next(
        (
            activity for activity in activities
            if isinstance(activity.metadata_json, dict)
            and str(activity.metadata_json.get("intensity", "")).lower() in {"easy", "moderate", "hard"}
        ),
        None,
    )
    def signal(value: datetime | None) -> dict[str, Any]:
        return {
            "state": "unknown" if value is None else ("stale" if current_time - value > timedelta(hours=72) else "fresh"),
            "data_through": value.isoformat() if value else None,
        }
    signals = {
        "activities": signal(activity_time),
        "sleep": signal(sleep_time),
        "intensity": signal(_utc(intensity_activity.start_time) if intensity_activity else None),
    }
    if activities and intensity_activity is None:
        missing.append("intensity")
    if freshness_state == "fresh" and any(item["state"] != "fresh" for item in signals.values()):
        freshness_state = "partial"
        freshness_label = "Some signals need a refresh"
    if signals["sleep"]["state"] == "stale":
        missing.append("current_sleep")

    latest_signals = (
        latest_recovery.get("signals", {})
        if isinstance(latest_recovery, dict)
        else {}
    )
    sleep_duration = latest_signals.get("sleep_duration", {})
    sleep_score = latest_signals.get("sleep_score", {})
    overnight_hrv = latest_signals.get("overnight_hrv", {})
    recovery_state = athlete_state.get("state", "unknown")
    recovery = {
        "state": "available" if recovery_state == "fresh" else recovery_state,
        "label": (
            "Latest recovery"
            if recovery_state == "fresh"
            else "Latest recovery is stale"
            if recovery_state == "stale"
            else "Recovery data unavailable"
        ),
        "sleep_hours": sleep_duration.get("value"),
        "sleep_score": sleep_score.get("value"),
        "overnight_hrv": overnight_hrv.get("value"),
    }
    training_consistency = _training_consistency(activities, current_time)
    readiness = {
        "state": "unknown", "score": None, "label": "Readiness unavailable",
        "explanation": "Training consistency alone cannot establish readiness; current recovery and intensity signals are needed.",
    }
    decision = athlete_state.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    coaching = _coaching_from_decision(decision)

    return {
        "state": "ready" if activities else "empty",
        "generated_at": current_time.isoformat(),
        "data_through": data_through.isoformat() if data_through else None,
        "freshness": {
            "state": freshness_state,
            "label": freshness_label,
            "missing": missing,
            "signals": signals,
        },
        "goal": _goal(goal),
        "readiness": readiness,
        "training_consistency": training_consistency,
        "recovery": recovery,
        "decision": decision,
        "trend": _trend(activities, current_time),
        "recent_activities": [_activity_payload(activity) for activity in activities[:5]],
        "coaching": coaching,
        "dossier": _dossier(dossier_artifacts, dossier_jobs),
    }
