# ruff: noqa: E501
# pylint: disable=line-too-long
"""REST endpoints that expose InfluxDB-derived training metrics."""

from __future__ import annotations

from fastapi import APIRouter

from .influx_utils import (
    RUN_TYPE_LABELS,
    first_non_null,
    get_average_cadence,
    get_elevation_gain,
    get_elevation_stats,
    get_influx_client,
)

router = APIRouter()


@router.get("/weekly-summary")
def weekly_summary(days: int = 7):
    """Aggregated distance, calories, and resting HR within the window."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT SUM("distance") AS distance, SUM("calories") AS calories '
        f'FROM "ActivitySummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    stats = result[0] if result else {"distance": 0, "calories": 0}

    hr_query = (
        'SELECT MEAN("restingHeartRate") AS rhr FROM "DailyStats" '
        f'WHERE time >= now() - {window}d'
    )
    hr_result = list(client.query(hr_query).get_points())
    stats["resting_hr"] = hr_result[0]["rhr"] if hr_result else None
    stats["window_days"] = window
    return stats


@router.get("/sleep-summary")
def sleep_summary(days: int = 7):
    """Average sleep, stress, HRV, SpO2, and stage durations within the window."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT MEAN("sleepTimeSeconds") AS sleep, '
        'MEAN("avgSleepStress") AS stress, '
        'MEAN("avgOvernightHrv") AS hrv, '
        'MEAN("averageSpO2Value") AS spo2_avg, '
        'MIN("lowestSpO2Value") AS spo2_low, '
        'MAX("highestSpO2Value") AS spo2_high, '
        'MEAN("restingHeartRate") AS resting_hr, '
        'MEAN("deepSleepSeconds") AS deep, '
        'MEAN("lightSleepSeconds") AS light, '
        'MEAN("remSleepSeconds") AS rem, '
        'MEAN("awakeSleepSeconds") AS awake '
        f'FROM "SleepSummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"window_days": window}
    row = result[0]
    return {
        "sleep_seconds": row.get("sleep"),
        "avg_sleep_stress": row.get("stress"),
        "avg_hrv": row.get("hrv"),
        "spo2_average": row.get("spo2_avg"),
        "spo2_low": row.get("spo2_low"),
        "spo2_high": row.get("spo2_high"),
        "resting_heart_rate": row.get("resting_hr"),
        "deep_sleep_seconds": row.get("deep"),
        "light_sleep_seconds": row.get("light"),
        "rem_sleep_seconds": row.get("rem"),
        "awake_sleep_seconds": row.get("awake"),
        "window_days": window,
    }


@router.get("/vo2-trend")
def vo2_trend(days: int = 30):
    """Latest and average VO2 max over a rolling window."""
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT LAST("VO2_max_value") AS latest, MEAN("VO2_max_value") AS average '
        f'FROM "VO2_Max" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"latest": None, "average": None, "window_days": window}
    row = result[0]
    latest = row.get("latest")
    avg = row.get("average")
    return {"latest": latest, "average": avg, "window_days": window}


@router.get("/hrv-trend")
def hrv_trend(days: int = 30):
    """Latest and average overnight HRV values."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("avgOvernightHrv") AS latest, MEAN("avgOvernightHrv") AS average '
        f'FROM "SleepSummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {"latest": None, "average": None}
    payload["window_days"] = window
    return payload


@router.get("/last-run")
def last_run():
    """Most recent running activity with summary metrics and dynamics."""
    client = get_influx_client()
    query = (
        'SELECT * FROM "ActivitySummary" '
        "WHERE activityType = 'running' "
        "OR activityType = 'treadmill_running' "
        "OR activityType = 'trail_running' "
        "ORDER BY time DESC LIMIT 1"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    activity_id = row.get("Activity_ID") or row.get("activityId")
    elev_gain = get_elevation_gain(client, int(activity_id)) if activity_id else None
    elev_stats = get_elevation_stats(client, int(activity_id)) if activity_id else {}
    return {
        "activity_id": activity_id,
        "activity": row,
        "run_type": RUN_TYPE_LABELS.get(row.get("activityType"), row.get("activityType")),
        "elevation_gain_m": elev_gain,
        "elevation_stats": elev_stats,
        "average_cadence": get_average_cadence(client, row),
        "max_cadence": None,
    }


@router.get("/recovery-score")
def recovery_score():
    """Latest body battery change and sleep stress metrics."""
    client = get_influx_client()
    query = (
        'SELECT LAST("bodyBatteryChange") AS body_battery, '
        'LAST("avgSleepStress") AS sleep_stress '
        'FROM "SleepSummary" WHERE time >= now() - 7d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"body_battery": None, "sleep_stress": None}
    row = result[0]
    return {
        "body_battery_change": row.get("body_battery"),
        "sleep_stress": row.get("sleep_stress"),
    }


def _score_training_row(row: dict) -> int:
    """Return a score representing how complete an activity summary row is."""
    score = 0
    if row.get("activityType"):
        score += 2
        if row.get("activityType") != "No Activity":
            score += 1
    for key in ("distance", "averageSpeed", "averageHR", "calories"):
        if row.get(key) is not None:
            score += 1
    return score


def _dedupe_training_rows(client, rows: list[dict], limit: int) -> list[dict]:
    """Remove duplicate activity rows while enriching cadence/elevation."""
    best_by_id: dict[str, dict] = {}
    for row in rows:
        activity_id = row.get("Activity_ID") or row.get("activityId")
        if activity_id is None:
            continue
        row_score = _score_training_row(row)
        existing = best_by_id.get(str(activity_id))
        if existing is None or row_score > _score_training_row(existing):
            best_by_id[str(activity_id)] = row

    deduped: list[dict] = []
    for row in sorted(best_by_id.values(), key=lambda r: r.get("time", ""), reverse=True):
        if len(deduped) >= limit:
            break
        run_type = row.get("activityType")
        entry = dict(row)
        activity_id = row.get("Activity_ID") or row.get("activityId")
        entry["activity_id"] = activity_id
        entry["run_label"] = RUN_TYPE_LABELS.get(run_type, run_type)
        entry["average_cadence"] = get_average_cadence(client, row)
        entry["elevation_gain_m"] = first_non_null(
            get_elevation_gain(client, int(activity_id)),
            row.get("totalElevationGain"),
        )
        elev = get_elevation_stats(client, int(activity_id))
        entry["elevation_gain_m"] = first_non_null(entry.get("elevation_gain_m"), elev.get("ascent"))
        entry["elevation_loss_m"] = elev.get("descent")
        entry["elevation_min_m"] = elev.get("min")
        entry["elevation_max_m"] = elev.get("max")
        speed_mps = row.get("averageSpeed")
        if speed_mps and speed_mps > 0:
            entry["avg_pace_sec_per_km"] = 1000.0 / speed_mps
            entry["avg_pace_sec_per_mile"] = 1609.34 / speed_mps
        for key in (
            "averageRunCadence",
            "avgRunCadence",
            "averageCadence",
            "avgCadence",
            "Activity_ID",
            "activityId",
            "strideLength",
            "verticalOscillation",
            "groundContactTime",
            "groundContactBalance",
            "stanceTimePercent",
        ):
            entry.pop(key, None)
        if entry.get("elevation_gain_m") is not None:
            entry.pop("totalElevationGain", None)
        deduped.append(entry)
    return deduped


@router.get("/training-log")
def training_log(limit: int = 20, days: int = 42):
    """Recent activities within a window with enrichment for cadence and elevation."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "distance","elapsedDuration","movingDuration","averageSpeed","averageHR","calories",'
        '"activityType","totalElevationGain","trainingEffectLabel","activityId","Activity_ID","averageRunCadence","avgRunCadence",'
        '"averageCadence","avgCadence","strideLength","verticalOscillation","groundContactTime",'
        '"groundContactBalance","stanceTimePercent" '
        f'FROM "ActivitySummary" WHERE time >= now() - {window}d '
        "ORDER BY time DESC LIMIT {}".format(int(limit * 2))
    )
    result = list(client.query(query).get_points())
    deduped = _dedupe_training_rows(client, result, limit)
    return {"window_days": window, "entries": deduped}


@router.get("/training-load")
def training_load_focus(days: int = 14):
    """Latest low/high aerobic and anaerobic load values over the window."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("lowAerobicLoad") AS low, LAST("highAerobicLoad") AS high, '
        'LAST("anaerobicLoad") AS anaerobic FROM "TrainingStatus" '
        f"WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {"low": None, "high": None, "anaerobic": None}
    payload["window_days"] = window
    return payload


@router.get("/running-dynamics")
def running_dynamics(days: int = 30):
    """Most recent running dynamics: cadence, stride, oscillation, contact time."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "averageRunCadence","strideLength","verticalOscillation",'
        '"groundContactTime","activityId" FROM "ActivitySummary" '
        f"WHERE activityType = 'running' AND time >= now() - {window}d "
        "ORDER BY time DESC LIMIT 1"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    return {
        "activity_id": row.get("activityId") or row.get("Activity_ID"),
        "average_cadence": get_average_cadence(client, row),
        "stride_length": row.get("strideLength"),
        "vertical_oscillation": row.get("verticalOscillation"),
        "ground_contact_time": row.get("groundContactTime"),
    }


@router.get("/recovery-time")
def recovery_time(days: int = 7):
    """Latest prescribed recovery time from Training Status."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("recoveryTime") AS hours FROM "TrainingStatus" '
        f"WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    return {
        "recovery_time_hours": result[0]["hours"] if result else None,
        "window_days": window,
    }


@router.get("/sleep-metrics")
def sleep_metrics(days: int = 7):
    """Most recent sleep stage durations, resting HR, and score."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("sleepTimeSeconds") AS sleep, LAST("deepSleepSeconds") AS deep, LAST("lightSleepSeconds") AS light, '
        'LAST("remSleepSeconds") AS rem, LAST("awakeSleepSeconds") AS awake, '
        'LAST("restingHeartRate") AS resting_hr, LAST("overallScore") AS score '
        f"FROM \"SleepSummary\" WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"window_days": window}
    row = result[0]
    return {
        "sleep": row.get("sleep"),
        "deep_sleep_seconds": row.get("deep"),
        "light_sleep_seconds": row.get("light"),
        "rem_sleep_seconds": row.get("rem"),
        "awake_sleep_seconds": row.get("awake"),
        "resting_heart_rate": row.get("resting_hr"),
        "score": row.get("score"),
        "window_days": window,
    }


@router.get("/stress-battery")
def stress_battery(days: int = 7):
    """Combined stress percentage and body battery charge/drain metrics."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT MEAN("stressPercentage") AS stress_pct, MEAN("bodyBatteryCharged") AS charged, '
        'MEAN("bodyBatteryDrained") AS drained FROM "DailyStats" '
        f"WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    row = result[0] if result else {}
    return {
        "stress_percentage": row.get("stress_pct") if row.get("stress_pct") is not None else row.get("stress"),
        "body_battery_charged": row.get("charged"),
        "body_battery_drained": row.get("drained"),
        "window_days": window,
    }


@router.get("/lactate-threshold")
def lactate_threshold():
    """Most recent threshold heart rate and pace."""
    client = get_influx_client()
    query = (
        'SELECT LAST("thresholdHeartRate") AS hr, LAST("thresholdPace") AS pace '
        'FROM "LactateThreshold" ORDER BY time DESC LIMIT 1'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    heart_rate = row.get("hr") if row.get("hr") is not None else row.get("heart_rate")
    pace_val = row.get("pace")
    return {"threshold_hr": heart_rate, "heart_rate": heart_rate, "threshold_pace": pace_val, "pace": pace_val}


@router.get("/race-predictions")
def race_predictions(days: int = 30):
    """Latest estimated finish times for common race distances."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("distance5k") AS time5K, LAST("distance10k") AS time10K, '
        'LAST("distanceHalfMarathon") AS half, LAST("distanceMarathon") AS marathon '
        f"FROM \"RacePrediction\" WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    row = result[0] if result else {}
    row["window_days"] = window
    return row


@router.get("/race-schedule")
def race_schedule(limit: int = 5, days: int = 365):
    """Upcoming calendar items with location and start time."""
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "eventName","location","startTimeLocal" FROM "RaceSchedule" '
        f"WHERE time <= now() + {window}d ORDER BY time ASC LIMIT {limit}"
    )
    result = list(client.query(query).get_points())
    return {"entries": result, "window_days": window}
