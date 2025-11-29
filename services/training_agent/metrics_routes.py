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
    distance_query = (
        'SELECT SUM("distance") AS distance, SUM("calories") AS calories '
        f'FROM "garmin_activity_summary" WHERE time >= now() - {window}d'
    )
    row = _mean(distance_query, client)
    rhr_query = (
        'SELECT MEAN("resting_hr") AS rhr '
        f'FROM "garmin_sleep_summary" WHERE time >= now() - {window}d'
    )
    rhr_row = _mean(rhr_query, client)
    return {
        "distance": row.get("distance"),
        "calories": row.get("calories"),
        "resting_hr": rhr_row.get("rhr"),
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
    row = {
        **row,
        "activity_id": row.get("activity_id") or row.get("Activity_ID") or row.get("activityId") or row.get("id"),
        "sport_type": row.get("sport_type") or row.get("activityType"),
        "stride_length": row.get("stride_length") or row.get("strideLength"),
        "elapsed_duration": row.get("elapsed_duration") or row.get("elapsedDuration"),
        "moving_duration": row.get("moving_duration") or row.get("movingDuration"),
        "average_hr": row.get("average_hr") or row.get("averageHR"),
    }
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
    return {"activity_id": activity_id, "average_cadence": avg_cad, "activity": summary}


@router.get("/recovery-score")
def recovery_score():
    """
    Latest body battery change and sleep stress metrics.
    Note: body battery is not currently written by the new pipeline; returns sleep stress only.
    """
    client = get_influx_client()
    query = (
        'SELECT LAST("body_battery") AS body_battery_change, LAST("avg_sleep_stress") AS sleep_stress '
        'FROM "garmin_sleep_summary" WHERE time >= now() - 7d'
    )
    row = _mean(query, client)
    return {
        "body_battery_change": row.get("body_battery_change") or row.get("body_battery"),
        "sleep_stress": row.get("sleep_stress") or row.get("sleep_stress_avg"),
    }


@router.get("/training-load")
def training_load():
    """Latest aerobic/anaerobic training load components."""
    client = get_influx_client()
    query = (
        'SELECT LAST("low") AS low, LAST("high") AS high, LAST("anaerobic") AS anaerobic '
        'FROM "garmin_training_load" WHERE time >= now() - 7d'
    )
    row = _mean(query, client)
    return {
        "low": row.get("low"),
        "high": row.get("high"),
        "anaerobic": row.get("anaerobic"),
    }


@router.get("/running-dynamics")
def running_dynamics():
    """Latest running dynamics sample (cadence, stride, contact time)."""
    client = get_influx_client()
    query = 'SELECT * FROM "garmin_running_dynamics" ORDER BY time DESC LIMIT 1'
    row = _mean(query, client)
    return {
        "activity_id": row.get("activity_id") or row.get("activityId"),
        "average_cadence": row.get("averageRunCadence") or row.get("average_cadence") or row.get("cadence"),
        "stride_length": row.get("strideLength") or row.get("stride_length"),
        "vertical_oscillation": row.get("verticalOscillation") or row.get("vertical_oscillation"),
        "ground_contact_time": row.get("groundContactTime") or row.get("ground_contact_time"),
    }


@router.get("/recovery-time")
def recovery_time():
    """Latest recommended recovery time."""
    client = get_influx_client()
    query = 'SELECT LAST("hours") AS hours FROM "garmin_recovery_time"'
    row = _mean(query, client)
    return {"recovery_time_hours": row.get("hours") or row.get("recovery_time_hours")}


@router.get("/sleep-metrics")
def sleep_metrics():
    """Sleep summary metrics (avg/deep/light/rem/awake)."""
    client = get_influx_client()
    query = 'SELECT * FROM "garmin_sleep_summary" ORDER BY time DESC LIMIT 1'
    row = _mean(query, client)
    return {
        "sleep": row.get("sleep") or row.get("sleepTimeSeconds"),
        "deep": row.get("deep") or row.get("deepSleepSeconds"),
        "light": row.get("light") or row.get("lightSleepSeconds"),
        "rem": row.get("rem") or row.get("remSleepSeconds"),
        "awake": row.get("awake"),
        "score": row.get("score"),
        "resting_hr": row.get("rhr") or row.get("resting_hr"),
    }


@router.get("/stress-battery")
def stress_battery():
    """Stress/battery summary."""
    client = get_influx_client()
    query = 'SELECT LAST("stress") AS stress FROM "garmin_stress_battery"'
    row = _mean(query, client)
    return {"stress_percentage": row.get("stress")}


@router.get("/lactate-threshold")
def lactate_threshold():
    """Latest lactate threshold metrics."""
    client = get_influx_client()
    query = 'SELECT LAST("heart_rate") AS heart_rate, LAST("pace") AS pace FROM "garmin_lactate_threshold"'
    row = _mean(query, client)
    return {"heart_rate": row.get("heart_rate"), "pace": row.get("pace")}


@router.get("/race-predictions")
def race_predictions():
    """Race prediction times (5k/10k/half/marathon)."""
    client = get_influx_client()
    query = 'SELECT * FROM "garmin_race_predictions" ORDER BY time DESC LIMIT 1'
    row = _mean(query, client)
    return {
        "time5K": row.get("time5K"),
        "time10K": row.get("time10K"),
        "half": row.get("half"),
        "marathon": row.get("marathon"),
    }


@router.get("/race-schedule")
def race_schedule():
    """Upcoming race schedule entries."""
    client = get_influx_client()
    query = 'SELECT * FROM "garmin_race_schedule" ORDER BY time DESC LIMIT 20'
    rows = list(client.query(query).get_points())
    return {"entries": rows}


@router.get("/training-log")
def training_log(days: int = 42):
    """Recent training log entries with simple dedupe and pace calc."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT * FROM "garmin_activity_summary" '
        f"WHERE time >= now() - {window}d ORDER BY time DESC"
    )
    rows = list(client.query(query).get_points())
    seen = set()
    entries = []
    for row in rows:
        activity_id = row.get("activity_id") or row.get("Activity_ID") or row.get("activityId") or row.get("id")
        if activity_id in seen:
            continue
        seen.add(activity_id)
        distance = row.get("distance")
        speed = row.get("averageSpeed") or row.get("average_speed") or row.get("average_speed_mps")
        pace = (1000.0 / speed) if speed and speed > 0 else None
        run_label = "Outdoor run" if str(row.get("activityType") or row.get("sport_type") or "").lower().startswith("run") else "Activity"
        entries.append(
            {
                "activity_id": activity_id,
                "time": row.get("time"),
                "distance_m": distance,
                "avg_pace_sec_per_km": pace,
                "run_label": run_label,
            }
        )
    return {"window_days": window, "entries": entries}
