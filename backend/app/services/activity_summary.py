"""Canonical Postgres-backed product metrics summary helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from app.models import Activity


FRESHNESS_WINDOW = timedelta(hours=72)
logger = logging.getLogger("services.activity_summary")


def _utc(value: datetime) -> datetime:
    """Normalize persisted timestamps before comparing or serializing them."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _empty_summary(current_time: datetime, state: str) -> dict[str, Any]:
    """Return a summary whose unavailable values cannot be mistaken for zero."""
    metric_states = {
        metric: state
        for metric in (
            "mileage",
            "average_weekly_mileage",
            "long_run_max",
            "hrv_avg",
            "pace_histogram",
            "training_load",
        )
    }
    result: dict[str, Any] = {
        "source": "canonical_postgres",
        "state": state,
        "generated_at": current_time.isoformat(),
        "data_through": None,
        "stale_after": None,
        "metric_states": metric_states,
        "mileage": {"30d": None, "60d": None, "90d": None},
        "average_weekly_mileage": None,
        "long_run_max": None,
        "hrv_avg": None,
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
        return _empty_summary(current_time, "error")

    if not activities:
        return _empty_summary(current_time, "unknown")

    activities.sort(key=lambda activity: _utc(activity.start_time), reverse=True)
    data_through = _utc(activities[0].start_time)
    stale_after = data_through + FRESHNESS_WINDOW
    state = "stale" if current_time > stale_after else "fresh"

    def _window_distance(days: int) -> float:
        cutoff = current_time - timedelta(days=days)
        return sum(
            float(getattr(activity, "distance_m", 0) or 0)
            for activity in activities
            if getattr(activity, "start_time", None) is not None
            and _utc(activity.start_time) >= cutoff
        )

    mileage_totals = {window: _window_distance(window) for window in (30, 60, 90)}
    long_run_max = max(
        (float(getattr(activity, "distance_m", 0) or 0) for activity in activities),
        default=0.0,
    )

    return {
        "source": "canonical_postgres",
        "state": state,
        "generated_at": current_time.isoformat(),
        "data_through": data_through.isoformat(),
        "stale_after": stale_after.isoformat(),
        "metric_states": {
            "mileage": state,
            "average_weekly_mileage": state,
            "long_run_max": state,
            "hrv_avg": "unknown",
            "pace_histogram": "unknown",
            "training_load": "unknown",
        },
        "mileage": {f"{window}d": value for window, value in mileage_totals.items()},
        "average_weekly_mileage": mileage_totals[90] / 12,
        "long_run_max": long_run_max,
        "hrv_avg": None,
        "pace_histogram": None,
        "training_load": None,
        "error": None,
    }
