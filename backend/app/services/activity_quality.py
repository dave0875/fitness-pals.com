"""Conservative validation shared by ingestion and athlete-facing reads."""

from __future__ import annotations

import math
from typing import Any


RUN_SPORTS = {
    "run", "running", "treadmill_running", "trail_running", "track_running",
    "indoor_running",
}
NON_DISTANCE_SPORTS = {"strength", "strength_training", "weight_training"}
# Values above a million metres for one activity are not credible workout distances.
# Garmin's 21,474,836 m sentinel is well beyond this bound.
MAX_ACTIVITY_DISTANCE_M = 1_000_000


def valid_distance_m(value: Any, sport: str | None) -> float | None:
    """Return a credible measured distance, or unknown without inventing zero."""
    if (sport or "").strip().lower() in NON_DISTANCE_SPORTS:
        return None
    try:
        distance = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(distance) or distance < 0 or distance >= MAX_ACTIVITY_DISTANCE_M:
        return None
    return distance


def is_run(sport: str | None) -> bool:
    """Limit running-specific coaching metrics to recognized running sports."""
    return (sport or "").strip().lower() in RUN_SPORTS
