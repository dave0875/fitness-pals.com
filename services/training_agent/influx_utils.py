# ruff: noqa: E501
# pylint: disable=line-too-long
"""InfluxDB helper queries for training agent metrics."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, cast

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError

logger = logging.getLogger("training_agent.influx")

RUN_TYPE_LABELS = {
    "running": "Outdoor run",
    "treadmill_running": "Treadmill run",
    "trail_running": "Trail run",
}


def _query_points(client: InfluxDBClient, query: str) -> list[dict]:
    """Execute a query and return list of point dictionaries."""
    result = client.query(query)
    points_iter = cast(Any, result).get_points()
    return list(points_iter)


def get_influx_client() -> InfluxDBClient:
    """Create an InfluxDB client using environment-based configuration."""
    return InfluxDBClient(
        host=os.environ.get("INFLUXDB_HOST", "influxdb"),
        port=int(os.environ.get("INFLUXDB_PORT", "8086")),
        username=os.environ.get("INFLUXDB_USERNAME", "influxdb_user"),
        password=os.environ.get("INFLUXDB_PASSWORD", "influxdb_secret_password"),
        database=os.environ.get("INFLUXDB_DATABASE", "GarminStats"),
        timeout=10,
    )


def resolve_cadence(row: dict) -> Optional[float]:
    """Garmin activities sometimes store cadence under different keys."""
    for key in (
        "averageRunCadence",
        "avgRunCadence",
        "averageCadence",
        "avgCadence",
        "cadence",
    ):
        value = row.get(key)
        if value is not None:
            return value
    return None


def fetch_cadence_from_gps(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    """Fetch average cadence from GPS samples when summary cadence is missing."""
    query = (
        'SELECT MEAN("Cadence") AS cadence, MEAN("Fractional_Cadence") AS fractional '
        f'FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}'
    )
    points = _query_points(client, query)
    if not points:
        return None
    cadence = points[0].get("cadence")
    if cadence is None:
        return None
    fractional = points[0].get("fractional") or 0
    return cadence + fractional


def get_average_cadence(client: InfluxDBClient, row: dict) -> Optional[float]:
    """Resolve cadence across summary, lap, and GPS sources."""
    cadence = resolve_cadence(row)
    if cadence is not None:
        return cadence
    activity_id = row.get("Activity_ID") or row.get("activityId")
    if not activity_id:
        return None
    try:
        lap_query = (
            'SELECT MEAN("Avg_Cadence") AS cadence FROM "ActivityLap" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
        )
        lap_points = _query_points(client, lap_query)
        lap_cadence = lap_points[0].get("cadence") if lap_points else None
        if lap_cadence is not None:
            return lap_cadence
        return fetch_cadence_from_gps(client, int(activity_id))
    except (ValueError, TypeError):
        return None


def get_elevation_gain(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    """Return total positive elevation gain for an activity, if available."""
    try:
        summary = _query_points(
            client,
            f'SELECT "totalElevationGain" FROM "ActivitySummary" WHERE "Activity_ID" = {int(activity_id)} LIMIT 1',
        )
        if summary:
            gain = summary[0].get("totalElevationGain")
            if gain is not None:
                return gain

        q = (
            'SELECT SUM("alt_diff") AS gain FROM ('
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff > 0"
        )
        points = _query_points(client, q)
        if points:
            return points[0].get("gain")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Elevation gain query failed",
            extra={
                "activity_id": activity_id,
                "error": str(err),
                "error_type": type(err).__name__,
            },
        )
        return None
    return None


def first_non_null(*values):
    """Return the first non-null value from a list of candidates."""
    for v in values:
        if v is not None:
            return v
    return None


def get_elevation_stats(
    client: InfluxDBClient, activity_id: int
) -> dict[str, Optional[float]]:
    """Return ascent, descent, min, and max elevation for an activity."""
    stats = {"ascent": None, "descent": None, "min": None, "max": None}
    try:
        base = _query_points(
            client,
            f'SELECT MIN("Altitude") AS min_alt, MAX("Altitude") AS max_alt '
            f'FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}',
        )
        if base:
            stats["min"] = base[0].get("min_alt")
            stats["max"] = base[0].get("max_alt")

        ascent_q = (
            'SELECT SUM("alt_diff") AS gain FROM ('
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff > 0"
        )
        ascent = _query_points(client, ascent_q)
        if ascent:
            stats["ascent"] = ascent[0].get("gain")

        descent_q = (
            'SELECT SUM("alt_diff") AS loss FROM ('
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff < 0"
        )
        descent = _query_points(client, descent_q)
        if descent:
            loss = descent[0].get("loss")
            stats["descent"] = abs(loss) if loss is not None else None
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Elevation stats query failed",
            extra={"activity_id": activity_id, "error": str(err), "partial": stats},
        )
        return stats
    return stats


def get_temperature_stats(
    client: InfluxDBClient, activity_id: int
) -> dict[str, Optional[float]]:
    """Return avg/min/max temperature for an activity if available."""
    stats = {"avg": None, "min": None, "max": None}
    try:
        temps = _query_points(
            client,
            f'SELECT MEAN("Temperature") AS avg_temp, MIN("Temperature") AS min_temp, '
            f'MAX("Temperature") AS max_temp FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}',
        )
        if temps:
            row = temps[0]
            stats["avg"] = row.get("avg_temp")
            stats["min"] = row.get("min_temp")
            stats["max"] = row.get("max_temp")
        if stats["avg"] is None:
            lap = _query_points(
                client,
                f'SELECT MEAN("Avg_Temperature") AS avg_temp FROM "ActivityLap" WHERE "Activity_ID" = {int(activity_id)}',
            )
            if lap:
                stats["avg"] = lap[0].get("avg_temp")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Temperature stats query failed",
            extra={"activity_id": activity_id, "error": str(err), "partial": stats},
        )
        return stats
    return stats


def get_max_cadence(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    """Return max cadence using GPS or lap aggregates."""
    try:
        gps = _query_points(
            client,
            f'SELECT MAX("Cadence") AS max_cadence FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}',
        )
        if gps and gps[0].get("max_cadence") is not None:
            return gps[0].get("max_cadence")
        lap = _query_points(
            client,
            f'SELECT MAX("Avg_Cadence") AS max_cadence FROM "ActivityLap" WHERE "Activity_ID" = {int(activity_id)}',
        )
        if lap:
            return lap[0].get("max_cadence")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Max cadence query failed",
            extra={
                "activity_id": activity_id,
                "error": str(err),
                "error_type": type(err).__name__,
            },
        )
        return None
    return None
