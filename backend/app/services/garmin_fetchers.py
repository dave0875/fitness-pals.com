"""
Helper functions to pull multiple Garmin data categories via garth and write to Influx.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging

from app.services.influx import get_influx_client_for_user

logger = logging.getLogger("garmin_fetchers")
logger.setLevel(logging.INFO)

# Categories roughly mirroring the garmin-grafana FETCH_SELECTION
CATEGORIES = [
    "daily_avg",
    "sleep",
    "steps",
    "heartrate",
    "stress",
    "breathing",
    "HRV",
    "fitness_age",
    "VO2",
    "race_prediction",
    "body_composition",
    "training_status",
    "training_readiness",
    "hill_score",
    "endurance_score",
    "solar_intensity",
    "steps_epoch",
    "distance_epoch",
    "active_time_epoch",
    "deep_sleep_duration",
    "light_sleep_duration",
    "rem_sleep_duration",
    "awake_duration",
    "validation_sleep",
    "avg_stress_level",
    "max_stress_level",
    "stress_duration_seconds",
    "low_stress_duration",
    "medium_stress_duration",
    "high_stress_duration",
    "pulse_ox",
    "respiration_rate",
    "body_battery",
    "lactate_threshold_estimate",
    "stride_length",
    "cadence",
    "ground_contact_time",
    "vertical_oscillation",
    "elevation_gain",
    "elevation_loss",
]


def _infer_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """Keep numeric/string fields as-is; skip nested structures."""
    fields: Dict[str, Any] = {}
    for k, v in item.items():
        if k in ("time",):
            continue
        if isinstance(v, (int, float, str)) or v is None:
            fields[k] = v
    return fields


def write_points(db, user, run, client, measurement: str, records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0
    write_api = client.write_api()
    points = []
    for item in records:
        fields = _infer_fields(item)
        if not fields:
            continue
        point = {
            "measurement": measurement,
            "tags": {
                "user_id": str(user.id),
                "ingest_run_id": str(run.id),
                "provider": "garmin",
            },
            "fields": fields,
        }
        points.append(point)
    if points:
        write_api.write(bucket=client.default_bucket, org=client.org, record=points)
    return len(points)


def fetch_and_write_categories(db, user, run, garth_client, categories: List[str] = None) -> Dict[str, int]:
    """Fetch each category via garth connectapi and write to Influx."""
    categories = categories or CATEGORIES
    summary: Dict[str, int] = {}
    try:
        client = get_influx_client_for_user(db, user.id)
    except Exception:
        # No Influx configured; skip silently
        return summary
    for cat in categories:
        try:
            logger.info(
                "garmin category fetch",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "run_id": str(getattr(run, "id", "")),
                    "category": cat,
                },
            )
            data = garth_client.connectapi(cat)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "garmin category fetch failed",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "run_id": str(getattr(run, "id", "")),
                    "category": cat,
                    "error": str(exc),
                },
            )
            continue
        records = data if isinstance(data, list) else [data]
        written = write_points(db, user, run, client, cat, records)
        summary[cat] = written
        logger.info(
            "garmin category written",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "run_id": str(getattr(run, "id", "")),
                "category": cat,
                "written": written,
            },
        )
    return summary
