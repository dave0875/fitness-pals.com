# ruff: noqa: E501
# pylint: disable=line-too-long
"""REST endpoints exposing metrics from the new Garmin Influx measurements."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .influx_utils import (
    RUN_TYPE_LABELS,
    first_non_null,
    get_average_cadence,
    get_elevation_gain,
    get_elevation_stats,
    get_influx_client,
)

router = APIRouter()


def _mean(query: str, client):
    result = list(client.query(query).get_points())
    return result[0] if result else {}


@router.get("/weekly-summary")
def weekly_summary(days: int = 7):
    """Aggregated distance and calories from activity summary within the window."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT SUM("distance") AS distance, SUM("calories") AS calories '
        f'FROM "garmin_activity_summary" WHERE time >= now() - {window}d'
    )
    row = _mean(query, client)
    return {
        "distance": row.get("distance"),
        "calories": row.get("calories"),
        "window_days": window,
    }


@router.get("/sleep-summary")
def sleep_summary(days: int = 7):
    """Average sleep durations and stress/HRV within the window."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT MEAN("sleep_time_seconds") AS sleep, '
        'MEAN("avg_sleep_stress") AS stress, '
        'MEAN("average_respiration_value") AS respiration, '
        'MEAN("deep_sleep_seconds") AS deep, '
        'MEAN("light_sleep_seconds") AS light, '
        'MEAN("rem_sleep_seconds") AS rem '
        f'FROM "garmin_sleep_summary" WHERE time >= now() - {window}d'
    )
    row = _mean(query, client)
    return {
        "sleep_seconds": row.get("sleep"),
        "avg_sleep_stress": row.get("stress"),
        "avg_respiration": row.get("respiration"),
        "deep_sleep_seconds": row.get("deep"),
        "light_sleep_seconds": row.get("light"),
        "rem_sleep_seconds": row.get("rem"),
        "window_days": window,
    }


@router.get("/vo2-trend")
def vo2_trend(days: int = 30):
    """Latest and average VO2 max over a rolling window from daily VO2."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT LAST("vo2max_value") AS latest, MEAN("vo2max_value") AS average '
        f'FROM "garmin_daily_vo2max" WHERE time >= now() - {window}d'
    )
    row = _mean(query, client)
    return {
        "latest": row.get("latest"),
        "average": row.get("average"),
        "window_days": window,
    }


@router.get("/hrv-trend")
def hrv_trend(days: int = 30):
    """Latest and average overnight HRV values from hrv_status."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("last_night_avg") AS latest, MEAN("weekly_avg") AS weekly_avg '
        f'FROM "garmin_hrv_status" WHERE time >= now() - {window}d'
    )
    row = _mean(query, client)
    return {
        "latest": row.get("latest"),
        "weekly_avg": row.get("weekly_avg"),
        "window_days": window,
    }


@router.get("/last-run")
def last_run():
    """Most recent running activity with summary metrics and dynamics."""
    client = get_influx_client()
    query = (
        'SELECT * FROM "garmin_activity_summary" '
        "WHERE sport_type = 'running' OR sport_type = 'treadmill_running' OR sport_type = 'trail_running' "
        "ORDER BY time DESC LIMIT 1"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    activity_id = row.get("activity_id")
    if not activity_id:
        return {}
    elev_stats = get_elevation_stats(client, int(activity_id)) if activity_id else {}
    elev_gain = first_non_null(
        get_elevation_gain(client, int(activity_id)) if activity_id else None,
        row.get("elevation_gain_m"),
        elev_stats.get("ascent"),
    )
    elev_loss = first_non_null(row.get("elevation_loss_m"), elev_stats.get("descent"))
    avg_cad = first_non_null(
        row.get("average_running_cadence_in_steps_per_minute"),
        row.get("average_cadence"),
        get_average_cadence(client, row),
    )
    max_cad = first_non_null(
        row.get("max_running_cadence_in_steps_per_minute"),
        row.get("max_cadence"),
        row.get("max_double_cadence"),
    )
    speed_mps = first_non_null(row.get("average_speed"))
    pace_per_km = 1000.0 / speed_mps if speed_mps and speed_mps > 0 else None
    pace_per_mile = 1609.34 / speed_mps if speed_mps and speed_mps > 0 else None
    duration_s = first_non_null(row.get("duration"), row.get("elapsed_duration"), row.get("moving_duration"))
    summary = {
        "activity_id": activity_id,
        "run_type": RUN_TYPE_LABELS.get(row.get("sport_type"), row.get("sport_type")),
        "time": row.get("time"),
        "sport_type": row.get("sport_type"),
        "activity_name": row.get("activity_name"),
        "distance_m": row.get("distance"),
        "duration_s": duration_s,
        "moving_duration_s": row.get("moving_duration"),
        "elapsed_duration_s": row.get("elapsed_duration"),
        "calories": row.get("calories"),
        "average_hr": row.get("average_hr"),
        "max_hr": row.get("max_hr"),
        "average_speed_mps": speed_mps,
        "max_speed_mps": row.get("max_speed"),
        "avg_pace_sec_per_km": pace_per_km,
        "avg_pace_sec_per_mile": pace_per_mile,
        "average_cadence_spm": avg_cad,
        "max_cadence_spm": max_cad,
        "stride_length_m": row.get("stride_length"),
        "vertical_oscillation_cm": row.get("vertical_oscillation"),
        "vertical_ratio": row.get("vertical_ratio"),
        "ground_contact_time_ms": row.get("ground_contact_time"),
        "training_load": row.get("training_load"),
        "aerobic_training_effect": row.get("aerobic_training_effect"),
        "anaerobic_training_effect": row.get("anaerobic_training_effect"),
        "hr_time_in_z1_s": row.get("hr_time_in_z1_s"),
        "hr_time_in_z2_s": row.get("hr_time_in_z2_s"),
        "hr_time_in_z3_s": row.get("hr_time_in_z3_s"),
        "hr_time_in_z4_s": row.get("hr_time_in_z4_s"),
        "hr_time_in_z5_s": row.get("hr_time_in_z5_s"),
        "elevation_gain_m": elev_gain,
        "elevation_loss_m": elev_loss,
        "elevation_min_m": elev_stats.get("min"),
        "elevation_max_m": elev_stats.get("max"),
        "device_name": row.get("device_name"),
        "device_id": row.get("device_id"),
        "manufacturer": row.get("manufacturer"),
    }
    return {"activity_id": activity_id, "activity": summary}


@router.get("/recovery-score")
def recovery_score():
    """
    Latest body battery change and sleep stress metrics.
    Note: body battery is not currently written by the new pipeline; returns sleep stress only.
    """
    client = get_influx_client()
    query = (
        'SELECT LAST("avg_sleep_stress") AS sleep_stress '
        'FROM "garmin_sleep_summary" WHERE time >= now() - 7d'
    )
    row = _mean(query, client)
    return {
        "body_battery_change": None,
        "sleep_stress": row.get("sleep_stress"),
    }
