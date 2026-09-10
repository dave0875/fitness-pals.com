# ruff: noqa: E501
# pylint: disable=line-too-long
"""User-scoped training endpoints backed by canonical Postgres fitness data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import fmean
from typing import Any

from fastapi import APIRouter, Depends

from .training_data import (
    Athlete,
    CanonicalTrainingStore,
    get_current_athlete,
    get_training_store,
)

router = APIRouter()

RUN_TYPES = {"running", "run", "treadmill_running", "trail_running"}
RUN_TYPE_LABELS = {
    "running": "Outdoor run",
    "run": "Outdoor run",
    "treadmill_running": "Treadmill run",
    "trail_running": "Trail run",
}


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _activity_payload(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata_json")
    merged = dict(metadata) if isinstance(metadata, dict) else {}
    merged.update(
        {
            "id": row.get("id"),
            "user_id": row.get("user_id"),
            "start_time": row.get("start_time"),
            "duration_seconds": row.get("duration_seconds"),
            "distance_m": row.get("distance_m"),
            "sport": row.get("sport"),
        }
    )
    return merged


def _sleep_payload(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("summary_json")
    return dict(summary) if isinstance(summary, dict) else {}


def _nested_or_self(payload: dict[str, Any], key: str) -> dict[str, Any]:
    nested = payload.get(key)
    return nested if isinstance(nested, dict) else payload


def _values(rows: list[dict[str, Any]], *keys: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _first(row, *keys)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _average(rows: list[dict[str, Any]], *keys: str) -> float | None:
    values = _values(rows, *keys)
    return fmean(values) if values else None


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(days, 1))


@router.get("/weekly-summary")
def weekly_summary(
    days: int = 7,
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Aggregate the authenticated athlete's canonical activity and sleep data."""
    window = max(days, 1)
    activities = [
        _activity_payload(row)
        for row in store.activities(athlete.id, since=_since(window))
    ]
    sleeps = [
        _sleep_payload(row)
        for row in store.sleep_sessions(athlete.id, since=_since(window).date())
    ]
    return {
        "distance": sum(_values(activities, "distance_m", "distance")),
        "calories": sum(_values(activities, "calories")),
        "resting_hr": _average(sleeps, "restingHeartRate", "resting_hr", "rhr"),
        "window_days": window,
    }


@router.get("/sleep-summary")
def sleep_summary(
    days: int = 7,
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Average canonical sleep summaries for the authenticated athlete."""
    window = max(days, 1)
    rows = [
        _sleep_payload(row)
        for row in store.sleep_sessions(athlete.id, since=_since(window).date())
    ]
    return {
        "sleep_seconds": _average(rows, "sleepTimeSeconds", "totalSleepSeconds", "sleep"),
        "avg_sleep_stress": _average(rows, "avgSleepStress", "avg_sleep_stress", "stress"),
        "avg_respiration": _average(rows, "averageRespirationValue", "average_respiration_value", "respiration"),
        "deep_sleep_seconds": _average(rows, "deepSleepSeconds", "deep_sleep_seconds", "deep"),
        "light_sleep_seconds": _average(rows, "lightSleepSeconds", "light_sleep_seconds", "light"),
        "rem_sleep_seconds": _average(rows, "remSleepSeconds", "rem_sleep_seconds", "rem"),
        "window_days": window,
    }


@router.get("/vo2-trend")
def vo2_trend(
    days: int = 30,
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return VO2 values present in the athlete's canonical activity metadata."""
    window = max(days, 1)
    rows = [
        _activity_payload(row)
        for row in store.activities(athlete.id, since=_since(window))
    ]
    values = _values(rows, "vo2maxValue", "vo2max_value", "vo2Max")
    return {
        "latest": values[0] if values else None,
        "average": fmean(values) if values else None,
        "window_days": window,
    }


@router.get("/hrv-trend")
def hrv_trend(
    days: int = 30,
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return HRV values from the athlete's canonical sleep summaries."""
    window = max(days, 1)
    rows = [
        _sleep_payload(row)
        for row in store.sleep_sessions(athlete.id, since=_since(window).date())
    ]
    nightly = _values(rows, "avgOvernightHrv", "last_night_avg", "hrv")
    weekly = _values(rows, "weeklyAvg", "weekly_avg")
    return {
        "latest": nightly[0] if nightly else None,
        "weekly_avg": fmean(weekly or nightly) if weekly or nightly else None,
        "window_days": window,
    }


def _running_rows(store: CanonicalTrainingStore, athlete: Athlete, *, limit: int = 100):
    return [
        _activity_payload(row)
        for row in store.activities(athlete.id, limit=limit)
        if str(row.get("sport") or "").lower() in RUN_TYPES
    ]


@router.get("/last-run")
def last_run(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return the authenticated athlete's latest canonical running activity."""
    rows = _running_rows(store, athlete)
    if not rows:
        return {}
    row = rows[0]
    activity_id = row.get("id")
    sport = str(row.get("sport") or "").lower()
    speed_mps = _first(row, "averageSpeed", "average_speed", "average_speed_mps")
    distance = _first(row, "distance_m", "distance")
    duration = _first(row, "duration_seconds", "duration", "elapsedDuration", "movingDuration")
    if speed_mps is None and distance and duration:
        speed_mps = float(distance) / float(duration)
    average_cadence = _first(row, "averageRunCadence", "average_cadence", "avgCadence", "cadence")
    summary = {
        "activity_id": activity_id,
        "run_type": RUN_TYPE_LABELS.get(sport, (sport or "Activity").replace("_", " ").title()),
        "time": row.get("start_time"),
        "sport_type": row.get("sport"),
        "activity_name": _first(row, "name", "activityName", "activity_name"),
        "distance_m": distance,
        "duration_s": duration,
        "moving_duration_s": _first(row, "movingDuration", "moving_duration"),
        "elapsed_duration_s": _first(row, "elapsedDuration", "elapsed_duration"),
        "calories": row.get("calories"),
        "average_hr": _first(row, "averageHR", "average_hr"),
        "max_hr": _first(row, "maxHR", "max_hr"),
        "average_speed_mps": speed_mps,
        "max_speed_mps": _first(row, "maxSpeed", "max_speed"),
        "avg_pace_sec_per_km": 1000.0 / float(speed_mps) if speed_mps and float(speed_mps) > 0 else None,
        "avg_pace_sec_per_mile": 1609.34 / float(speed_mps) if speed_mps and float(speed_mps) > 0 else None,
        "average_cadence_spm": average_cadence,
        "max_cadence_spm": _first(row, "maxRunCadence", "max_cadence", "maxCadence"),
        "stride_length_m": _first(row, "strideLength", "stride_length"),
        "vertical_oscillation_cm": _first(row, "verticalOscillation", "vertical_oscillation"),
        "vertical_ratio": _first(row, "verticalRatio", "vertical_ratio"),
        "ground_contact_time_ms": _first(row, "groundContactTime", "ground_contact_time"),
        "training_load": _first(row, "trainingLoad", "training_load"),
        "aerobic_training_effect": _first(row, "aerobicTrainingEffect", "aerobic_training_effect"),
        "anaerobic_training_effect": _first(row, "anaerobicTrainingEffect", "anaerobic_training_effect"),
        "elevation_gain_m": _first(row, "totalElevationGain", "elevationGain", "elevation_gain_m"),
        "elevation_loss_m": _first(row, "elevationLoss", "elevation_loss_m"),
        "device_name": _first(row, "deviceName", "device_name"),
        "device_id": _first(row, "deviceId", "device_id"),
        "manufacturer": row.get("manufacturer"),
    }
    return {"activity_id": activity_id, "average_cadence": average_cadence, "activity": summary}


@router.get("/recovery-score")
def recovery_score(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return recovery signals from the athlete's latest canonical sleep row."""
    rows = store.sleep_sessions(athlete.id, limit=1)
    row = _sleep_payload(rows[0]) if rows else {}
    return {
        "body_battery_change": _first(row, "bodyBatteryChange", "body_battery_change", "body_battery"),
        "sleep_stress": _first(row, "avgSleepStress", "sleep_stress", "sleep_stress_avg"),
    }


@router.get("/training-load")
def training_load(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return latest training load values from canonical activity metadata."""
    rows = store.activities(athlete.id, since=_since(7), limit=1)
    row = _activity_payload(rows[0]) if rows else {}
    load = _nested_or_self(row, "trainingLoad")
    return {
        "low": _first(load, "low", "lowAerobic"),
        "high": _first(load, "high", "highAerobic"),
        "anaerobic": load.get("anaerobic"),
    }


@router.get("/running-dynamics")
def running_dynamics(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return running dynamics from the latest canonical run."""
    rows = _running_rows(store, athlete)
    row = rows[0] if rows else {}
    return {
        "activity_id": row.get("id"),
        "average_cadence": _first(row, "averageRunCadence", "average_cadence", "cadence"),
        "stride_length": _first(row, "strideLength", "stride_length"),
        "vertical_oscillation": _first(row, "verticalOscillation", "vertical_oscillation"),
        "ground_contact_time": _first(row, "groundContactTime", "ground_contact_time"),
    }


@router.get("/recovery-time")
def recovery_time(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return recommended recovery time from latest canonical activity metadata."""
    rows = store.activities(athlete.id, limit=1)
    row = _activity_payload(rows[0]) if rows else {}
    return {"recovery_time_hours": _first(row, "recoveryTimeHours", "recovery_time_hours", "hours")}


@router.get("/sleep-metrics")
def sleep_metrics(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return the authenticated athlete's latest canonical sleep summary."""
    rows = store.sleep_sessions(athlete.id, limit=1)
    row = _sleep_payload(rows[0]) if rows else {}
    return {
        "sleep": _first(row, "sleepTimeSeconds", "totalSleepSeconds", "sleep"),
        "deep": _first(row, "deepSleepSeconds", "deep"),
        "light": _first(row, "lightSleepSeconds", "light"),
        "rem": _first(row, "remSleepSeconds", "rem"),
        "awake": _first(row, "awakeSleepSeconds", "awake"),
        "score": _first(row, "sleepScore", "overallSleepScore", "score"),
        "resting_hr": _first(row, "restingHeartRate", "resting_hr", "rhr"),
    }


@router.get("/stress-battery")
def stress_battery(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return stress from the latest canonical sleep summary."""
    rows = store.sleep_sessions(athlete.id, limit=1)
    row = _sleep_payload(rows[0]) if rows else {}
    return {"stress_percentage": _first(row, "stress", "avgSleepStress", "avg_sleep_stress")}


@router.get("/lactate-threshold")
def lactate_threshold(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return lactate threshold fields from canonical activity metadata."""
    rows = store.activities(athlete.id, limit=1)
    row = _activity_payload(rows[0]) if rows else {}
    threshold = _nested_or_self(row, "lactateThreshold")
    return {
        "heart_rate": _first(threshold, "heartRate", "heart_rate"),
        "pace": threshold.get("pace"),
    }


@router.get("/race-predictions")
def race_predictions(
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return race predictions only when present in canonical activity metadata."""
    rows = store.activities(athlete.id, limit=1)
    row = _activity_payload(rows[0]) if rows else {}
    predictions = _nested_or_self(row, "racePredictions")
    return {
        "time5K": predictions.get("time5K"),
        "time10K": predictions.get("time10K"),
        "half": predictions.get("half"),
        "marathon": predictions.get("marathon"),
    }


@router.get("/race-schedule")
def race_schedule(
    _athlete: Athlete = Depends(get_current_athlete),
):
    """Represent unavailable race schedules without consulting global storage."""
    return {"entries": []}


@router.get("/training-log")
def training_log(
    days: int = 42,
    athlete: Athlete = Depends(get_current_athlete),
    store: CanonicalTrainingStore = Depends(get_training_store),
):
    """Return canonical activities belonging only to the authenticated athlete."""
    window = max(days, 1)
    rows = [
        _activity_payload(row)
        for row in store.activities(athlete.id, since=_since(window))
    ]
    entries = []
    for row in rows:
        distance = _first(row, "distance_m", "distance")
        duration = _first(row, "duration_seconds", "duration")
        speed = _first(row, "averageSpeed", "average_speed", "average_speed_mps")
        if speed is None and distance and duration:
            speed = float(distance) / float(duration)
        sport = str(row.get("sport") or "").lower()
        entries.append(
            {
                "activity_id": row.get("id"),
                "time": row.get("start_time"),
                "distance_m": distance,
                "avg_pace_sec_per_km": 1000.0 / float(speed) if speed and float(speed) > 0 else None,
                "run_label": RUN_TYPE_LABELS.get(sport, (sport or "Activity").replace("_", " ").title()),
            }
        )
    return {"window_days": window, "entries": entries}
