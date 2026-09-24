"""Canonical Postgres-backed product metrics summary helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from app.models import Activity
from app.services.activity_quality import is_run, valid_distance_m
from app.services.athlete_state import build_athlete_state


FRESHNESS_WINDOW = timedelta(hours=72)
logger = logging.getLogger("services.activity_summary")


def _utc(value: datetime) -> datetime:
    """Normalize persisted timestamps before comparing or serializing them."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hrv_compat(athlete_state: dict[str, Any]) -> tuple[float | None, str, int]:
    """Bridge the legacy hrv_avg field to canonical Athlete State evidence."""
    derived = athlete_state.get("derived") if isinstance(athlete_state, dict) else {}
    hrv = derived.get("hrv_7d_average") if isinstance(derived, dict) else {}
    if not isinstance(hrv, dict):
        return None, "unknown", 0
    value = hrv.get("value")
    sample_count = int(hrv.get("sample_count") or 0)
    status = str(hrv.get("status") or "")
    metric_state = {"known": "fresh", "stale": "stale"}.get(status, "unknown")
    return value, metric_state, sample_count


def _empty_summary(
    current_time: datetime,
    state: str,
    athlete_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a summary whose unavailable values cannot be mistaken for zero."""
    canonical_state = athlete_state or {
        "source": "canonical_postgres",
        "state": "unknown",
        "generated_at": current_time.isoformat(),
        "data_through": None,
        "latest": None,
        "history": [],
        "derived": {
            "hrv_7d_average": {
                "value": None,
                "unit": "ms",
                "status": "unavailable",
                "window_days": 7,
                "sample_count": 0,
            }
        },
        "error": None,
    }
    hrv_avg, hrv_state, sample_count = _hrv_compat(canonical_state)
    metric_states = {
        metric: state
        for metric in (
            "mileage",
            "average_weekly_mileage",
            "long_run_max",
            "pace_histogram",
            "training_load",
        )
    }
    metric_states["hrv_avg"] = hrv_state
    result: dict[str, Any] = {
        "source": "canonical_postgres",
        "state": state,
        "generated_at": current_time.isoformat(),
        "data_through": None,
        "stale_after": None,
        "running_data_through": None,
        "metric_states": metric_states,
        "mileage": {"30d": None, "60d": None, "90d": None},
        "average_weekly_mileage": None,
        "long_run_max": None,
        "hrv_avg": hrv_avg,
        "hrv_avg_window_days": 7,
        "hrv_avg_sample_count": sample_count,
        "athlete_state": canonical_state,
        "training": canonical_state.get("training"),
        "future_intent": canonical_state.get("future_intent"),
        "pace_histogram": None,
        "training_load": None,
        "error": None,
    }
    if state == "error":
        result["error"] = {
            "code": "canonical_read_failed",
            "message": "Canonical fitness data is temporarily unavailable.",
        }
    return result


def build_canonical_summary(
    db, user_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Aggregate one athlete's product metrics exclusively from canonical rows."""
    current_time = _utc(now or datetime.now(timezone.utc))
    athlete_state = build_athlete_state(db, user_id, now=current_time, days=14)
    try:
        activities = [
            activity
            for activity in (
                db.query(Activity)
                .filter(Activity.user_id == user_id, Activity.status != "conflict")
                .all()
            )
            if getattr(activity, "user_id", None) == user_id
            and getattr(activity, "status", None) != "conflict"
        ]
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "canonical metrics query failed",
            extra={"user_id": str(user_id)},
        )
        return _empty_summary(current_time, "error", athlete_state)

    if not activities:
        return _empty_summary(current_time, "unknown", athlete_state)

    activities.sort(key=lambda activity: _utc(activity.start_time), reverse=True)
    data_through = _utc(activities[0].start_time)
    stale_after = data_through + FRESHNESS_WINDOW
    state = "stale" if current_time > stale_after else "fresh"

    runs = [activity for activity in activities if is_run(activity.sport)]
    known_runs = [
        activity
        for activity in runs
        if valid_distance_m(activity.distance_m, activity.sport) is not None
    ]
    latest_run_time = _utc(known_runs[0].start_time) if known_runs else None
    run_state = (
        "unknown" if latest_run_time is None
        else "stale" if current_time > latest_run_time + FRESHNESS_WINDOW
        else "fresh"
    )

    def _window_distance(days: int) -> float | None:
        cutoff = current_time - timedelta(days=days)
        distances = [
            valid_distance_m(activity.distance_m, activity.sport)
            for activity in runs
            if getattr(activity, "start_time", None) is not None
            and cutoff <= _utc(activity.start_time) <= current_time
        ]
        known = [value for value in distances if value is not None]
        return sum(known) if known else None

    mileage_totals = {window: _window_distance(window) for window in (30, 60, 90)}
    long_run_distances: list[float] = []
    for activity in known_runs:
        if not current_time - timedelta(days=90) <= _utc(activity.start_time) <= current_time:
            continue
        distance = valid_distance_m(activity.distance_m, activity.sport)
        if distance is not None:
            long_run_distances.append(distance)
    long_run_max = max(long_run_distances, default=None)
    distance_state = run_state if mileage_totals[30] is not None else "unknown"
    hrv_avg, hrv_state, hrv_sample_count = _hrv_compat(athlete_state)

    return {
        "source": "canonical_postgres",
        "state": state,
        "generated_at": current_time.isoformat(),
        "data_through": data_through.isoformat(),
        "stale_after": stale_after.isoformat(),
        "running_data_through": latest_run_time.isoformat() if latest_run_time else None,
        "metric_states": {
            "mileage": distance_state,
            "average_weekly_mileage": run_state if mileage_totals[90] is not None else "unknown",
            "long_run_max": run_state if long_run_max is not None else "unknown",
            "hrv_avg": hrv_state,
            "pace_histogram": "unknown",
            "training_load": "unknown",
        },
        "mileage": {f"{window}d": value for window, value in mileage_totals.items()},
        "average_weekly_mileage": mileage_totals[90] / 12 if mileage_totals[90] is not None else None,
        "long_run_max": long_run_max,
        "hrv_avg": hrv_avg,
        "hrv_avg_window_days": 7,
        "hrv_avg_sample_count": hrv_sample_count,
        "athlete_state": athlete_state,
        "training": athlete_state.get("training"),
        "future_intent": athlete_state.get("future_intent"),
        "pace_histogram": None,
        "training_load": None,
        "error": None,
    }
