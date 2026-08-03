"""Provider-neutral journey and activity-detail read models."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Activity, ActivitySource, SleepSession


WINDOW_DAYS = {"30d": 30, "90d": 90, "365d": 365}
GOAL_LABELS = {
    "marathon": "Marathon",
    "half": "Half marathon",
    "recovery": "Recovery",
    "consistency": "Consistency",
}
KNOWN_INTENSITIES = {"easy", "moderate", "hard"}


def _utc(value: datetime | date) -> datetime:
    """Normalize canonical timestamps for comparisons."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _window_start(window: str, now: datetime) -> datetime | None:
    """Return the inclusive start for a supported journey window."""
    days = WINDOW_DAYS.get(window)
    return now - timedelta(days=days) if days else None


def _activity_title(activity: Activity) -> str:
    """Return one allow-listed athlete-facing title."""
    metadata = activity.metadata_json if isinstance(activity.metadata_json, dict) else {}
    title = metadata.get("name") or metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"{(activity.sport or 'Activity').replace('_', ' ').title()}"


def _activity_intensity(activity: Activity) -> str | None:
    """Read a normalized intensity label when canonical metadata provides one."""
    metadata = activity.metadata_json if isinstance(activity.metadata_json, dict) else {}
    value = str(metadata.get("intensity", "")).lower()
    return value if value in KNOWN_INTENSITIES else None


def _activity_payload(activity: Activity) -> dict[str, Any]:
    """Serialize only canonical activity fields used by the journey UI."""
    return {
        "id": str(activity.id),
        "title": _activity_title(activity),
        "sport": activity.sport or "unknown",
        "start_time": _utc(activity.start_time).isoformat(),
        "distance_m": float(activity.distance_m) if activity.distance_m is not None else None,
        "duration_seconds": activity.duration_seconds,
        "intensity": _activity_intensity(activity),
        "status": activity.status,
    }


def _sleep_hours(session: SleepSession) -> float | None:
    """Extract sleep duration from supported canonical summary keys."""
    summary = session.summary_json if isinstance(session.summary_json, dict) else {}
    seconds = summary.get("sleepTimeSeconds")
    if seconds is None:
        seconds = summary.get("sleep_time_seconds")
    try:
        return round(float(seconds) / 3600.0, 2) if seconds is not None else None
    except (TypeError, ValueError):
        return None


def _period_summaries(
    activities: list[Activity],
    sleep_sessions: list[SleepSession],
    period: str,
) -> list[dict[str, Any]]:
    """Aggregate activities and recovery into reconciled calendar periods."""
    buckets: dict[date, dict[str, Any]] = defaultdict(
        lambda: {
            "activity_count": 0,
            "distance_m": 0.0,
            "duration_seconds": 0,
            "active_days": set(),
            "sleep_hours": [],
        }
    )

    def key_for(value: datetime | date) -> date:
        moment = _utc(value)
        if period == "month":
            return date(moment.year, moment.month, 1)
        return (moment - timedelta(days=moment.weekday())).date()

    for activity in activities:
        bucket = buckets[key_for(activity.start_time)]
        bucket["activity_count"] += 1
        bucket["distance_m"] += float(activity.distance_m or 0)
        bucket["duration_seconds"] += int(activity.duration_seconds or 0)
        bucket["active_days"].add(_utc(activity.start_time).date())

    for session in sleep_sessions:
        hours = _sleep_hours(session)
        if hours is not None:
            buckets[key_for(session.calendar_date)]["sleep_hours"].append(hours)

    result = []
    for period_start in sorted(buckets, reverse=True):
        bucket = buckets[period_start]
        sleep_values = bucket["sleep_hours"]
        result.append(
            {
                "period_start": period_start.isoformat(),
                "activity_count": bucket["activity_count"],
                "distance_m": round(bucket["distance_m"], 2),
                "duration_seconds": bucket["duration_seconds"],
                "active_days": len(bucket["active_days"]),
                "average_sleep_hours": (
                    round(sum(sleep_values) / len(sleep_values), 2)
                    if sleep_values
                    else None
                ),
            }
        )
    return result


def build_journey(
    db: Session,
    user_id: UUID,
    *,
    window: str = "90d",
    sport: str = "all",
    goal: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one athlete's filterable journey from canonical records."""
    current_time = _utc(now or datetime.now(timezone.utc))
    selected_window = window if window in {*WINDOW_DAYS, "all"} else "90d"
    selected_sport = sport.strip().lower() or "all"
    start = _window_start(selected_window, current_time)

    activities = [
        activity
        for activity in db.query(Activity).all()
        if getattr(activity, "user_id", None) == user_id
        and getattr(activity, "status", None) != "conflict"
        and (start is None or _utc(activity.start_time) >= start)
        and (selected_sport == "all" or (activity.sport or "").lower() == selected_sport)
    ]
    activities.sort(key=lambda item: _utc(item.start_time), reverse=True)

    sleep_sessions = [
        session
        for session in db.query(SleepSession).all()
        if getattr(session, "user_id", None) == user_id
        and (start is None or _utc(session.calendar_date) >= start)
    ]
    sleep_sessions.sort(key=lambda item: _utc(item.calendar_date), reverse=True)

    activity_payloads = [_activity_payload(activity) for activity in activities]
    known_intensities = [
        intensity
        for intensity in (_activity_intensity(activity) for activity in activities)
        if intensity is not None
    ]
    intensity_distribution = None
    if known_intensities:
        intensity_distribution = {
            key: known_intensities.count(key) for key in sorted(KNOWN_INTENSITIES)
        }

    data_candidates = [
        *(_utc(activity.start_time) for activity in activities[:1]),
        *(_utc(session.calendar_date) for session in sleep_sessions[:1]),
    ]
    data_through = max(data_candidates) if data_candidates else None
    missing = []
    if not activities:
        missing.append("activities")
    if not sleep_sessions:
        missing.append("sleep")
    if activities and not known_intensities:
        missing.append("intensity")

    if data_through is None:
        freshness_state = "empty"
    elif current_time - data_through > timedelta(hours=72):
        freshness_state = "stale"
    elif missing:
        freshness_state = "partial"
    else:
        freshness_state = "fresh"

    weekly = _period_summaries(activities, sleep_sessions, "week")
    monthly = _period_summaries(activities, sleep_sessions, "month")
    totals = {
        "activity_count": len(activity_payloads),
        "distance_m": round(
            sum(item["distance_m"] or 0 for item in activity_payloads), 2
        ),
        "duration_seconds": sum(
            item["duration_seconds"] or 0 for item in activity_payloads
        ),
        "active_days": len(
            {_utc(activity.start_time).date() for activity in activities}
        ),
        "intensity_distribution": intensity_distribution,
    }

    milestones = []
    if activities:
        longest = max(activities, key=lambda item: float(item.distance_m or 0))
        milestones.append(
            {
                "kind": "longest_activity",
                "label": "Longest activity in this window",
                "activity_id": str(longest.id),
                "distance_m": float(longest.distance_m or 0),
            }
        )
    if weekly:
        strongest = max(weekly, key=lambda item: item["distance_m"])
        milestones.append(
            {
                "kind": "highest_volume_week",
                "label": "Highest-volume week in this window",
                "period_start": strongest["period_start"],
                "distance_m": strongest["distance_m"],
            }
        )

    goal_payload = (
        {"key": goal, "label": GOAL_LABELS.get(goal, goal.replace("_", " ").title())}
        if goal
        else None
    )
    return {
        "filters": {
            "window": selected_window,
            "sport": selected_sport,
            "goal": goal or "all",
        },
        "window": {
            "start": start.isoformat() if start else None,
            "end": current_time.isoformat(),
        },
        "freshness": {
            "state": freshness_state,
            "data_through": data_through.isoformat() if data_through else None,
            "missing": missing,
        },
        "goal": goal_payload,
        "totals": totals,
        "weekly_summaries": weekly,
        "monthly_summaries": monthly,
        "milestones": milestones,
        "activities": activity_payloads,
    }


def build_activity_detail(
    db: Session,
    user_id: UUID,
    activity_id: UUID,
) -> dict[str, Any]:
    """Return a private canonical activity with allow-listed provenance."""
    activity = next(
        (
            item
            for item in db.query(Activity).all()
            if getattr(item, "id", None) == activity_id
            and getattr(item, "user_id", None) == user_id
        ),
        None,
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    sources = [
        source
        for source in db.query(ActivitySource).all()
        if getattr(source, "activity_id", None) == activity_id
    ]
    provenance = []
    for source in sources:
        chosen = source.chosen_fields if isinstance(source.chosen_fields, dict) else {}
        upstream = chosen.get("upstream_provider")
        if not isinstance(upstream, str):
            upstream = "garmin" if source.provider == "pulsai" else None
        source_timestamp = chosen.get("source_timestamp")
        provenance.append(
            {
                "provider": source.provider,
                "upstream_provider": upstream,
                "source_timestamp": (
                    source_timestamp if isinstance(source_timestamp, str) else None
                ),
            }
        )

    payload = _activity_payload(activity)
    missing = [
        key
        for key in ("distance_m", "duration_seconds", "intensity")
        if payload[key] is None
    ]
    return {
        "activity": payload,
        "provenance": provenance,
        "data_quality": {
            "state": "partial" if missing else "complete",
            "missing": missing,
        },
    }
