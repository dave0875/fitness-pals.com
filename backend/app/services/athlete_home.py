"""Canonical athlete-home read model composed from user-owned records."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from app.models import Activity, SleepSession, SyncCheckpoint

METERS_PER_MILE = 1609.344


def _utc(value: datetime | date | None) -> datetime | None:
    """Normalize persisted dates and datetimes for freshness comparisons."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    """Return the first present non-null value from a provider-neutral summary lookup."""
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


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
        "distance_m": float(activity.distance_m) if activity.distance_m is not None else None,
        "duration_seconds": activity.duration_seconds,
    }


def _recovery(latest_sleep: SleepSession | None) -> dict[str, Any]:
    """Build recovery facts while representing unavailable values as unknown."""
    if latest_sleep is None or not isinstance(latest_sleep.summary_json, dict):
        return {
            "state": "unknown",
            "label": "Recovery data unavailable",
            "sleep_hours": None,
            "sleep_score": None,
            "overnight_hrv": None,
        }

    summary = latest_sleep.summary_json
    sleep_seconds = _first_value(
        summary,
        "sleepTimeSeconds",
        "totalSleepSeconds",
        "durationSeconds",
    )
    score_payload = summary.get("sleepScores")
    score = score_payload.get("overall") if isinstance(score_payload, dict) else None
    if score is None:
        score = _first_value(summary, "sleepScore", "overallSleepScore")
    hrv = _first_value(summary, "avgOvernightHrv", "overnightHrv", "hrv")

    return {
        "state": "available",
        "label": "Latest recovery",
        "sleep_hours": round(float(sleep_seconds) / 3600, 1) if sleep_seconds is not None else None,
        "sleep_score": score,
        "overnight_hrv": hrv,
    }


def _trend(activities: list[Activity], now: datetime) -> dict[str, Any]:
    """Compare the latest seven training days with the preceding seven."""
    current_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)
    current_m = sum(
        float(activity.distance_m or 0)
        for activity in activities
        if _utc(activity.start_time) >= current_start
    )
    previous_m = sum(
        float(activity.distance_m or 0)
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


def _readiness(activities: list[Activity], now: datetime) -> dict[str, Any]:
    """Create an explainable readiness view from visible canonical training signals."""
    recent = [
        activity
        for activity in activities
        if _utc(activity.start_time) >= now - timedelta(days=30)
    ]
    if not recent:
        return {
            "state": "unknown",
            "score": None,
            "label": "Readiness unavailable",
            "explanation": "Recent activity history is needed before readiness can be estimated.",
        }

    mileage = sum(float(activity.distance_m or 0) for activity in recent) / METERS_PER_MILE
    active_days = len({_utc(activity.start_time).date() for activity in recent})
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


def _coaching(
    activities: list[Activity],
    recovery: dict[str, Any],
    freshness_state: str,
    now: datetime,
) -> dict[str, Any]:
    """Choose one next action and explain it from signals shown on the page."""
    recent_days = len(
        {
            _utc(activity.start_time).date()
            for activity in activities
            if _utc(activity.start_time) >= now - timedelta(days=7)
        }
    )
    if freshness_state == "stale":
        return {
            "insight": "Your training picture is out of date.",
            "explanation": "Refresh the connection before using older signals to change training.",
            "next_action": {"label": "Refresh fitness data", "href": "/welcome"},
        }
    if recovery["state"] == "available" and recovery["sleep_score"] is not None:
        if float(recovery["sleep_score"]) < 60:
            return {
                "insight": "Recovery should lead today.",
                "explanation": (
                    f"Your latest sleep score is {recovery['sleep_score']}; keep the next session "
                    "easy enough to protect tomorrow's training."
                ),
                "next_action": {"label": "Ask coach for a recovery session", "href": "/dashboard#coach"},
            }
    if recent_days >= 4:
        return {
            "insight": "Protect the consistency you have built.",
            "explanation": (
                f"You trained on {recent_days} of the last seven days. An easy day now helps "
                "that consistency compound instead of becoming accumulated fatigue."
            ),
            "next_action": {"label": "Plan an easy day", "href": "/dashboard#coach"},
        }
    return {
        "insight": "One calm training day adds useful signal.",
        "explanation": (
            f"You trained on {recent_days} of the last seven days. A conversational session "
            "is the clearest next step while your fitness picture develops."
        ),
        "next_action": {"label": "Ask coach about the next session", "href": "/dashboard#coach"},
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
        ],
        key=lambda activity: _utc(activity.start_time),
        reverse=True,
    )
    sleep_sessions = sorted(
        [
            session
            for session in db.query(SleepSession).all()
            if getattr(session, "user_id", None) == user_id
        ],
        key=lambda session: _utc(session.calendar_date),
        reverse=True,
    )
    checkpoints = [
        checkpoint
        for checkpoint in db.query(SyncCheckpoint).all()
        if getattr(checkpoint, "user_id", None) == user_id
    ]

    latest_sleep = sleep_sessions[0] if sleep_sessions else None
    data_candidates = [
        *(_utc(activity.start_time) for activity in activities[:1]),
        *(_utc(session.calendar_date) for session in sleep_sessions[:1]),
        *(
            _utc(checkpoint.last_synced_at)
            for checkpoint in checkpoints
            if checkpoint.last_synced_at is not None
        ),
    ]
    data_candidates = [candidate for candidate in data_candidates if candidate is not None]
    data_through = max(data_candidates) if data_candidates else None

    missing = []
    if not activities:
        missing.append("activities")
    if not sleep_sessions:
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

    recovery = _recovery(latest_sleep)
    readiness = _readiness(activities, current_time)
    coaching = _coaching(activities, recovery, freshness_state, current_time)

    return {
        "state": "ready" if activities else "empty",
        "generated_at": current_time.isoformat(),
        "data_through": data_through.isoformat() if data_through else None,
        "freshness": {
            "state": freshness_state,
            "label": freshness_label,
            "missing": missing,
        },
        "goal": _goal(goal),
        "readiness": readiness,
        "recovery": recovery,
        "trend": _trend(activities, current_time),
        "recent_activities": [_activity_payload(activity) for activity in activities[:5]],
        "coaching": coaching,
        "dossier": {
            "state": "not_generated",
            "title": "Your first coaching dossier",
            "summary": "Turn your recent training and recovery into a durable coaching narrative.",
            "action": {
                "label": "Ask coach to prepare it",
                "href": "/dashboard?prompt=Create%20my%20first%20coaching%20dossier#coach",
            },
        },
    }
