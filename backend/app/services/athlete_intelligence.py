"""Deterministic, athlete-scoped intelligence built from canonical product records."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from math import sqrt
import re
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException

from app.models import Activity, AthleteGoal, SleepSession
from app.services.activity_quality import is_run, valid_distance_m
from app.services.today_plan import build_today_context

METERS_PER_MILE = 1609.344
FRESHNESS_WINDOW = timedelta(hours=72)
MAX_ACTIVITY_ROWS = 400
MAX_SLEEP_ROWS = 180
MIN_ASSOCIATION_PAIRS = 6
MAX_PREFERENCES = 8
MAX_PREFERENCE_LENGTH = 160

_SCENARIO_MARKERS = (
    "what if",
    "hypothetical",
    "suppose ",
    "if i ",
    "if we ",
    "imagine ",
)


def _utc(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _owned_activities(db, user_id: UUID) -> list[Activity]:
    rows = (
        db.query(Activity)
        .filter(Activity.user_id == user_id)
        .order_by(Activity.start_time.desc())
        .limit(MAX_ACTIVITY_ROWS)
        .all()
    )
    return [
        row
        for row in rows
        if getattr(row, "user_id", None) == user_id
        and getattr(row, "status", None) != "conflict"
    ]


def _owned_sleep(db, user_id: UUID) -> list[SleepSession]:
    rows = (
        db.query(SleepSession)
        .filter(SleepSession.user_id == user_id)
        .order_by(SleepSession.calendar_date.desc())
        .limit(MAX_SLEEP_ROWS)
        .all()
    )
    return [row for row in rows if getattr(row, "user_id", None) == user_id]


def _goal_for(db, user_id: UUID) -> AthleteGoal | None:
    rows = (
        db.query(AthleteGoal)
        .filter(AthleteGoal.user_id == user_id)
        .order_by(AthleteGoal.updated_at.desc())
        .limit(1)
        .all()
    )
    return rows[0] if rows and getattr(rows[0], "user_id", None) == user_id else None


def _activity_distance_miles(activity: Activity) -> float | None:
    distance = valid_distance_m(activity.distance_m, activity.sport)
    return round(distance / METERS_PER_MILE, 2) if distance is not None else None


def _run_totals(
    activities: list[Activity], start: datetime, end: datetime
) -> dict[str, Any]:
    selected = [
        row
        for row in activities
        if is_run(row.sport) and start <= _utc(row.start_time) < end
    ]
    known_distance = [
        distance
        for row in selected
        if (distance := valid_distance_m(row.distance_m, row.sport)) is not None
    ]
    duration_seconds = sum(
        int(row.duration_seconds)
        for row in selected
        if row.duration_seconds is not None and row.duration_seconds > 0
    )
    longest = max(
        (_activity_distance_miles(row) for row in selected),
        default=None,
        key=lambda value: value if value is not None else -1,
    )
    return {
        "runs": len(selected),
        "miles": round(sum(known_distance) / METERS_PER_MILE, 1),
        "active_days": len({_utc(row.start_time).date() for row in selected}),
        "duration_minutes": round(duration_seconds / 60),
        "longest_run_miles": longest,
        "start": start.date().isoformat(),
        "end": (end - timedelta(microseconds=1)).date().isoformat(),
    }


def _percent_change(current: float | int, previous: float | int) -> float | None:
    if previous == 0:
        return None
    return round(((float(current) - float(previous)) / float(previous)) * 100.0, 1)


def _self_comparison(activities: list[Activity], now: datetime) -> dict[str, Any]:
    current = _run_totals(activities, now - timedelta(days=7), now)
    previous = _run_totals(activities, now - timedelta(days=14), now - timedelta(days=7))
    return {
        "state": "available" if current["runs"] or previous["runs"] else "insufficient",
        "basis": "Latest 7 days versus the preceding 7 days",
        "current": current,
        "previous": previous,
        "changes": {
            "miles_percent": _percent_change(current["miles"], previous["miles"]),
            "active_days": current["active_days"] - previous["active_days"],
            "duration_percent": _percent_change(
                current["duration_minutes"], previous["duration_minutes"]
            ),
            "longest_run_miles": (
                None
                if current["longest_run_miles"] is None
                or previous["longest_run_miles"] is None
                else round(
                    current["longest_run_miles"] - previous["longest_run_miles"], 2
                )
            ),
        },
    }


def _briefing(comparison: dict[str, Any]) -> dict[str, Any]:
    current = comparison["current"]
    previous = comparison["previous"]
    if comparison["state"] != "available":
        return {
            "state": "insufficient",
            "headline": "No recent running change can be measured yet.",
            "details": [
                "Canonical running history is needed in the latest two seven-day windows."
            ],
            "href": "/training",
        }

    details = [
        (
            f"{current['miles']:.1f} running miles across {current['active_days']} active "
            f"days in the latest 7 days."
        ),
        (
            f"The preceding 7 days contained {previous['miles']:.1f} miles across "
            f"{previous['active_days']} active days."
        ),
    ]
    change = comparison["changes"]["miles_percent"]
    if previous["miles"] == 0 and current["miles"] > 0:
        headline = "Recent running establishes a new seven-day baseline."
    elif change is None:
        headline = "Recent running volume is unchanged from a zero-mile baseline."
    elif change > 5:
        headline = f"Your seven-day running volume increased {abs(change):.0f}%."
    elif change < -5:
        headline = f"Your seven-day running volume decreased {abs(change):.0f}%."
    else:
        headline = "Your seven-day running volume is broadly steady."

    longest_change = comparison["changes"]["longest_run_miles"]
    if longest_change is not None and abs(longest_change) >= 0.5:
        direction = "longer" if longest_change > 0 else "shorter"
        details.append(
            f"Your longest run was {abs(longest_change):.1f} miles {direction} than in the prior window."
        )
    return {
        "state": "available",
        "headline": headline,
        "details": details,
        "href": "/progress?window=30d&sport=run&goal=all",
    }


def _sleep_hours(session: SleepSession) -> float | None:
    payload = session.summary_json if isinstance(session.summary_json, dict) else {}
    seconds = None
    for key in ("sleepTimeSeconds", "totalSleepSeconds", "durationSeconds", "sleep_time_seconds"):
        if payload.get(key) is not None:
            seconds = payload[key]
            break
    if seconds is None:
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value / 3600.0, 3)


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < MIN_ASSOCIATION_PAIRS:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, numerator / denominator))


def _sleep_run_association(
    activities: list[Activity], sleep_sessions: list[SleepSession]
) -> dict[str, Any]:
    sleep_by_date = {
        cast(date, row.calendar_date): hours
        for row in sleep_sessions
        if (hours := _sleep_hours(row)) is not None
    }
    running_minutes: dict[date, float] = defaultdict(float)
    for activity in activities:
        if not is_run(activity.sport):
            continue
        duration = activity.duration_seconds
        if duration is None or duration <= 0:
            continue
        running_minutes[_utc(activity.start_time).date()] += float(duration) / 60.0

    pairs = [
        (sleep_by_date[day], minutes)
        for day, minutes in sorted(running_minutes.items())
        if day in sleep_by_date
    ]
    sample_size = len(pairs)
    caveat = (
        "This is an athlete-to-self association in recorded data. It does not establish "
        "that sleep caused the running-time difference."
    )
    if sample_size < MIN_ASSOCIATION_PAIRS:
        return {
            "state": "insufficient",
            "title": "Sleep duration and same-day running time",
            "sample_size": sample_size,
            "minimum_sample": MIN_ASSOCIATION_PAIRS,
            "correlation": None,
            "direction": None,
            "strength": None,
            "caveat": (
                f"At least {MIN_ASSOCIATION_PAIRS} paired recorded days are required before "
                "showing an association. Missing days are not treated as zero."
            ),
            "href": "/progress?window=90d&sport=run&goal=all",
        }

    correlation = _pearson(pairs)
    if correlation is None:
        return {
            "state": "insufficient_variation",
            "title": "Sleep duration and same-day running time",
            "sample_size": sample_size,
            "minimum_sample": MIN_ASSOCIATION_PAIRS,
            "correlation": None,
            "direction": None,
            "strength": None,
            "caveat": (
                "The paired observations do not contain enough variation for a stable "
                "correlation. No causal conclusion is available."
            ),
            "href": "/progress?window=90d&sport=run&goal=all",
        }

    magnitude = abs(correlation)
    strength = "weak" if magnitude < 0.3 else "moderate" if magnitude < 0.6 else "strong"
    direction = "positive" if correlation > 0.05 else "negative" if correlation < -0.05 else "flat"
    return {
        "state": "available",
        "title": "Sleep duration and same-day running time",
        "sample_size": sample_size,
        "minimum_sample": MIN_ASSOCIATION_PAIRS,
        "correlation": round(correlation, 2),
        "direction": direction,
        "strength": strength,
        "caveat": caveat,
        "href": "/progress?window=90d&sport=run&goal=all",
    }


def _signal(value: datetime | None, now: datetime) -> dict[str, Any]:
    if value is None:
        return {"state": "unknown", "data_through": None}
    return {
        "state": "stale" if now - value > FRESHNESS_WINDOW else "fresh",
        "data_through": value.isoformat(),
    }


def _freshness(
    activities: list[Activity], sleep_sessions: list[SleepSession], now: datetime
) -> dict[str, Any]:
    latest_activity = max((_utc(row.start_time) for row in activities), default=None)
    latest_sleep = max(
        (_utc(cast(date, row.calendar_date)) for row in sleep_sessions),
        default=None,
    )
    activity_signal = _signal(latest_activity, now)
    sleep_signal = _signal(latest_sleep, now)
    states = {activity_signal["state"], sleep_signal["state"]}
    if states == {"unknown"}:
        state = "empty"
    elif "unknown" in states or len(states) > 1:
        state = "partial"
    else:
        state = next(iter(states))
    return {
        "state": state,
        "signals": {"activities": activity_signal, "sleep": sleep_signal},
    }


def _weekly_view(activities: list[Activity], now: datetime) -> dict[str, Any]:
    start = (now - timedelta(days=41)).date()
    buckets: dict[date, dict[str, Any]] = defaultdict(
        lambda: {"distance_m": 0.0, "known_distance": 0, "active_days": set(), "runs": 0}
    )
    for activity in activities:
        if not is_run(activity.sport):
            continue
        day = _utc(activity.start_time).date()
        if day < start:
            continue
        week = day - timedelta(days=day.weekday())
        bucket = buckets[week]
        bucket["runs"] += 1
        bucket["active_days"].add(day)
        distance = valid_distance_m(activity.distance_m, activity.sport)
        if distance is not None:
            bucket["distance_m"] += distance
            bucket["known_distance"] += 1

    points = []
    for week in sorted(buckets):
        bucket = buckets[week]
        points.append(
            {
                "week_start": week.isoformat(),
                "runs": bucket["runs"],
                "active_days": len(bucket["active_days"]),
                "miles": (
                    round(bucket["distance_m"] / METERS_PER_MILE, 1)
                    if bucket["known_distance"]
                    else None
                ),
            }
        )
    return {
        "type": "weekly_running_volume",
        "title": "Six-week running view",
        "points": points[-6:],
        "href": "/progress?window=90d&sport=run&goal=all",
        "note": "Generated from canonical runs; unknown distance stays unknown.",
    }


def _preferences(goal: AthleteGoal | None) -> list[str]:
    if goal is None or not isinstance(goal.intent_json, dict):
        return []
    raw = goal.intent_json.get("coaching_preferences")
    if not isinstance(raw, list):
        return []
    return [
        str(item).strip()[:MAX_PREFERENCE_LENGTH]
        for item in raw[:MAX_PREFERENCES]
        if isinstance(item, str) and item.strip()
    ]


def save_coaching_preferences(
    db, user_id: UUID, preferences: list[str]
) -> list[str]:
    """Persist only preferences the athlete explicitly submitted."""
    goal = _goal_for(db, user_id)
    if goal is None:
        raise HTTPException(
            status_code=409,
            detail="Choose a training goal before saving coaching preferences.",
        )

    cleaned: list[str] = []
    for item in preferences[:MAX_PREFERENCES]:
        value = " ".join(str(item).split()).strip()[:MAX_PREFERENCE_LENGTH]
        if value and value not in cleaned:
            cleaned.append(value)

    intent = dict(goal.intent_json or {})
    if cleaned:
        intent["coaching_preferences"] = cleaned
    else:
        intent.pop("coaching_preferences", None)
    goal.intent_json = intent
    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    return cleaned


def build_scenario_context(question: str) -> dict[str, Any] | None:
    """Recognize an explicit hypothetical without converting it into observed truth."""
    compact = " ".join((question or "").split()).strip()[:500]
    lowered = compact.lower()
    if not compact or not any(marker in lowered for marker in _SCENARIO_MARKERS):
        return None

    miles = re.search(r"(\d+(?:\.\d+)?)\s*(?:mile|miles|mi)\b", lowered)
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", lowered)
    requested_change: dict[str, Any] = {"question": compact}
    if miles:
        requested_change["mentioned_miles"] = float(miles.group(1))
    if percent:
        requested_change["mentioned_percent"] = float(percent.group(1))

    return {
        "state": "projection",
        "label": "Hypothetical scenario",
        "requested_change": requested_change,
        "caveat": (
            "Projection only. This scenario has not happened and must not be presented "
            "as an observed workout, recovery signal, or measured outcome."
        ),
    }


def build_athlete_intelligence(
    db, user_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Compose bounded intelligence from only this athlete's canonical records."""
    current_time = _utc(now or datetime.now(timezone.utc))
    activities = _owned_activities(db, user_id)
    sleep_sessions = _owned_sleep(db, user_id)
    goal = _goal_for(db, user_id)
    comparison = _self_comparison(activities, current_time)
    today_context = build_today_context(db, user_id, now=current_time)
    trajectory = today_context["trajectory"]

    return {
        "generated_at": current_time.isoformat(),
        "scope": "athlete_only",
        "briefing": _briefing(comparison),
        "athlete_to_self": comparison,
        "trajectory": trajectory,
        "future_intent": today_context["future_intent"],
        "freshness": _freshness(activities, sleep_sessions, current_time),
        "associations": [_sleep_run_association(activities, sleep_sessions)],
        "preferences": _preferences(goal),
        "views": [_weekly_view(activities, current_time)],
        "scenario_policy": {
            "label": "Hypothetical scenarios are projections",
            "detail": (
                "Coach must distinguish projected scenarios from observed canonical facts "
                "and keep uncertainty explicit."
            ),
        },
    }
