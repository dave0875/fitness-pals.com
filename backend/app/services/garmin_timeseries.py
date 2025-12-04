"""
Transform Garmin health bundle data into InfluxDB points.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from app.types import InfluxClientLike


def _base_tags(user, run, ingest_run_tag: str) -> Dict[str, str]:
    return {
        "user_id": str(getattr(user, "id", "")),
        "ingest_run_id": ingest_run_tag,
        "provider": "garmin",
    }


def _point(measurement: str, time: Any, fields: Dict[str, Any], tags: Dict[str, str]) -> Dict[str, Any]:
    clean_fields = {k: v for k, v in fields.items() if isinstance(v, (int, float, str)) or v is None}
    return {"measurement": measurement, "time": time, "fields": clean_fields, "tags": tags}


def _hrv_readings_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    readings: List[Dict[str, Any]] = []
    hrv_days = bundle.get("stats", {}).get("hrv_data")
    if not isinstance(hrv_days, list):
        return readings
    for day in hrv_days:
        if not isinstance(day, dict):
            continue
        hrv_values = day.get("hrv_readings") or []
        if not isinstance(hrv_values, list):
            continue
        for reading in hrv_values:
            if not isinstance(reading, dict):
                continue
            time_val = reading.get("reading_time_gmt") or reading.get("reading_time_local")
            readings.append(
                _point(
                    "garmin_hrv_readings",
                    time_val,
                    {"hrv_value": reading.get("hrv_value")},
                    tags,
                )
            )
    return readings


def _sleep_movement_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    sleep_days = bundle.get("stats", {}).get("sleep_data")
    if not isinstance(sleep_days, list):
        return points
    for day in sleep_days:
        if not isinstance(day, dict):
            continue
        movements = day.get("sleep_movement") or []
        if not isinstance(movements, list):
            continue
        for mv in movements:
            if not isinstance(mv, dict):
                continue
            points.append(
                _point(
                    "garmin_sleep_movement",
                    mv.get("start_gmt") or mv.get("start_timestamp_gmt"),
                    {"activity_level": mv.get("activity_level")},
                    tags,
                )
            )
    return points


def _sleep_summary_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    sleep_days = bundle.get("stats", {}).get("sleep_data")
    if not isinstance(sleep_days, list):
        return points
    for day in sleep_days:
        if not isinstance(day, dict):
            continue
        dto = day.get("daily_sleep_dto") or {}
        cal = dto.get("calendar_date")
        fields = {
            "sleep_time_seconds": dto.get("sleep_time_seconds"),
            "deep_sleep_seconds": dto.get("deep_sleep_seconds"),
            "light_sleep_seconds": dto.get("light_sleep_seconds"),
            "rem_sleep_seconds": dto.get("rem_sleep_seconds"),
            "avg_sleep_stress": dto.get("avg_sleep_stress"),
            "average_respiration_value": dto.get("average_respiration_value"),
        }
        points.append(_point("garmin_sleep_summary", cal, fields, tags))
    return points


def _daily_list_points(bundle: dict, key: str, measurement: str, field_map: Dict[str, str], tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    day_list = bundle.get("stats", {}).get(key)
    if not isinstance(day_list, list):
        return points
    for day in day_list:
        if not isinstance(day, dict):
            continue
        cal = day.get("calendar_date")
        fields = {out: day.get(inp) for inp, out in field_map.items()}
        points.append(_point(measurement, cal, fields, tags))
    return points


def _daily_vo2max_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    per_day = bundle.get("connectapi", {}).get("per_day", {}) or {}
    for cal, payloads in per_day.items():
        data = payloads.get("daily_vo2max")
        if not data or isinstance(data, dict) and data.get("error"):
            continue
        fields = {
            "vo2max_value": data.get("vO2MaxValue") or data.get("vo2MaxValue"),
            "vo2max_precise": data.get("vo2MaxPreciseValue"),
            "maxmet_category": data.get("maxMetCategory") or data.get("maxmetCategory"),
        }
        points.append(_point("garmin_daily_vo2max", cal, fields, tags))
    return points


def _weight_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    per_day = bundle.get("connectapi", {}).get("per_day", {}) or {}
    for cal, payloads in per_day.items():
        data = payloads.get("weight_range")
        if not data or isinstance(data, dict) and data.get("error"):
            continue
        weights = data if isinstance(data, list) else [data]
        for w in weights:
            fields = {
                "weight": w.get("weight"),
                "bmi": w.get("bmi"),
                "body_fat": w.get("bodyFat"),
            }
            points.append(_point("garmin_weight", cal, fields, tags))
    return points


def _acclimation_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    raw = bundle.get("connectapi", {}).get("multi_day", {}).get("acclimation")
    if not raw or (isinstance(raw, dict) and raw.get("error")):
        return []

    descriptor: List[Dict[str, Any]] = []
    values: list = []
    if isinstance(raw, dict):
        descriptor = raw.get("monitoringEnvironmentValueDescriptorList") or []
        val = raw.get("monitoringEnvironmentValuesArray") or raw.get("acclimationValues")
        if isinstance(val, list):
            values = val
    elif isinstance(raw, list):
        values = raw
    else:
        return []

    idx_map = {item["monEnvValueDescIndex"]: item["monEnvValueDescKey"] for item in descriptor if isinstance(item, dict) and "monEnvValueDescIndex" in item}

    points: List[Dict[str, Any]] = []
    for row in values:
        if isinstance(row, list):
            payload = {idx_map.get(i, f"v{i}"): row[i] for i in range(len(row))}
        elif isinstance(row, dict):
            payload = row
        else:
            continue
        ts = payload.get("timestamp")
        points.append(_point("garmin_acclimation", ts, payload, tags))
    return points


def _sleep_timeseries_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    per_day = bundle.get("connectapi", {}).get("per_day", {}) or {}
    for cal, payloads in per_day.items():
        data = payloads.get("sleep_timeseries")
        if not data or isinstance(data, dict) and data.get("error"):
            continue
        fields = {
            "total_sleep_seconds": data.get("sleepTimeSeconds"),
            "deep_sleep_seconds": data.get("deepSleepSeconds"),
            "light_sleep_seconds": data.get("lightSleepSeconds"),
            "rem_sleep_seconds": data.get("remSleepSeconds"),
            "average_stress": data.get("averageStress"),
        }
        points.append(_point("garmin_sleep_timeseries", cal, fields, tags))
    return points


def _activities_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    acts = bundle.get("connectapi", {}).get("multi_day", {}).get("activities")
    if not acts or isinstance(acts, dict) and acts.get("error"):
        return []
    records = acts.get("results") if isinstance(acts, dict) else acts
    points: List[Dict[str, Any]] = []
    for act in records or []:
        start_time = act.get("startTimeGMT") or act.get("startTimeGmt") or act.get("startTimeLocal")
        fields = {
            "activity_id": act.get("activityId"),
            "activity_name": act.get("activityName"),
            "sport_type": (act.get("activityType") or {}).get("typeKey"),
            "distance": act.get("distance"),
            "duration": act.get("duration"),
            "calories": act.get("calories"),
            "average_hr": act.get("averageHR") or act.get("avgHr") or act.get("avgHeartRate"),
            "max_hr": act.get("maxHR") or act.get("maxHeartRate"),
            "training_load": act.get("activityTrainingLoad"),
            "vo2max_value": act.get("vO2MaxValue") or act.get("vo2MaxValue"),
        }
        points.append(_point("garmin_activity_summary", start_time, fields, tags))
    return points


def _monthly_vo2max_points(bundle: dict, tags: Dict[str, str]) -> List[Dict[str, Any]]:
    monthly = bundle.get("connectapi", {}).get("multi_day", {}).get("monthly_vo2max") or []
    points: List[Dict[str, Any]] = []
    for item in monthly:
        gen = item.get("generic") or {}
        cal = gen.get("calendarDate") or item.get("calendarDate")
        fields = {
            "vo2max_value": gen.get("vo2MaxValue"),
            "vo2max_precise": gen.get("vo2MaxPreciseValue"),
            "fitness_age": gen.get("fitnessAge"),
            "fitness_age_description": gen.get("fitnessAgeDescription"),
        }
        points.append(_point("garmin_monthly_vo2max", cal, fields, tags))
    return points


def build_timeseries(bundle: dict, user, run, ingest_run_tag: str) -> List[Dict[str, Any]]:
    """
    Convert the health bundle into a list of Influx points.
    """
    tags = _base_tags(user, run, ingest_run_tag)
    points: List[Dict[str, Any]] = []
    points.extend(_hrv_readings_points(bundle, tags))
    points.extend(_sleep_movement_points(bundle, tags))
    points.extend(_sleep_summary_points(bundle, tags))
    points.extend(_daily_list_points(bundle, "sleep_score", "garmin_sleep_score", {"value": "value"}, tags))
    points.extend(_daily_list_points(bundle, "steps", "garmin_daily_steps", {"total_steps": "total_steps", "total_distance": "total_distance", "step_goal": "step_goal"}, tags))
    points.extend(_daily_list_points(bundle, "stress", "garmin_daily_stress", {"overall_stress_level": "overall_stress_level"}, tags))
    points.extend(_daily_list_points(bundle, "intensity_minutes", "garmin_intensity_minutes", {"moderate_value": "moderate_value", "vigorous_value": "vigorous_value", "weekly_goal": "weekly_goal"}, tags))
    points.extend(_daily_list_points(bundle, "hrv_status", "garmin_hrv_status", {"weekly_avg": "weekly_avg", "last_night_avg": "last_night_avg", "last_night_5_min_high": "last_night_5_min_high"}, tags))
    points.extend(_daily_vo2max_points(bundle, tags))
    points.extend(_weight_points(bundle, tags))
    points.extend(_sleep_timeseries_points(bundle, tags))
    points.extend(_acclimation_points(bundle, tags))
    points.extend(_activities_points(bundle, tags))
    points.extend(_monthly_vo2max_points(bundle, tags))
    return [p for p in points if p.get("fields")]


def write_timeseries(client: InfluxClientLike, points: List[Dict[str, Any]]):
    """Write a list of points to Influx."""
    if not points:
        return 0
    write_api = client.write_api()
    write_api.write(bucket=client.default_bucket, org=client.org, record=points)
    return len(points)
