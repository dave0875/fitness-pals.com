"""Canonical Postgres-backed metrics summary helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.models import Activity


def build_canonical_summary(
    db, user_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Aggregate metrics from canonical activity rows when Influx is unavailable."""
    current_time = now or datetime.now(timezone.utc)
    activities = [
        activity
        for activity in db.query(Activity).all()
        if getattr(activity, "user_id", None) == user_id
    ]

    def _window_distance(days: int) -> float:
        cutoff = current_time - timedelta(days=days)
        return sum(
            float(getattr(activity, "distance_m", 0) or 0)
            for activity in activities
            if getattr(activity, "start_time", None) is not None
            and activity.start_time >= cutoff
        )

    mileage_totals = {window: _window_distance(window) for window in (30, 60, 90)}
    long_run_max = max(
        (float(getattr(activity, "distance_m", 0) or 0) for activity in activities),
        default=0.0,
    )

    return {
        "mileage": {f"{window}d": value for window, value in mileage_totals.items()},
        "average_weekly_mileage": mileage_totals[90] / 12 if mileage_totals[90] else 0,
        "long_run_max": long_run_max,
        "hrv_avg": None,
        "pace_histogram": [],
        "training_load": [],
    }
