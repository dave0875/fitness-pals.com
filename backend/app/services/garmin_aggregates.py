"""
Build high-level aggregate summaries from the Garmin health bundle for Postgres storage.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _safe_list(bundle: dict, key: str) -> List[dict]:
    data = bundle.get("stats", {}).get(key)
    return data if isinstance(data, list) else []


def _sleep_aggregates(bundle: dict) -> List[dict]:
    items = []
    for day in _safe_list(bundle, "sleep_data"):
        dto = day.get("daily_sleep_dto") or {}
        items.append(
            {
                "calendar_date": dto.get("calendar_date"),
                "sleep_time_seconds": dto.get("sleep_time_seconds"),
                "deep_sleep_seconds": dto.get("deep_sleep_seconds"),
                "light_sleep_seconds": dto.get("light_sleep_seconds"),
                "rem_sleep_seconds": dto.get("rem_sleep_seconds"),
                "average_respiration_value": dto.get("average_respiration_value"),
                "avg_sleep_stress": dto.get("avg_sleep_stress"),
                "sleep_score": (dto.get("sleep_scores") or {}).get("overall", {}).get("value"),
                "sleep_feedback": dto.get("sleep_score_feedback") or dto.get("sleep_score_insight"),
            }
        )
    return items


def _hrv_aggregates(bundle: dict) -> List[dict]:
    items = []
    for day in _safe_list(bundle, "hrv_status"):
        items.append(
            {
                "calendar_date": day.get("calendar_date"),
                "status": day.get("status"),
                "weekly_avg": day.get("weekly_avg"),
                "last_night_avg": day.get("last_night_avg"),
                "last_night_5_min_high": day.get("last_night_5_min_high"),
                "feedback_phrase": day.get("feedback_phrase"),
            }
        )
    return items


def _vo2_aggregates(bundle: dict) -> Dict[str, Any]:
    per_day = bundle.get("connectapi", {}).get("per_day", {}) or {}
    daily = []
    for cal, payloads in per_day.items():
        data = payloads.get("daily_vo2max") or {}
        if isinstance(data, dict) and data.get("error"):
            continue
        daily.append(
            {
                "calendar_date": cal,
                "vo2max_value": data.get("vO2MaxValue") or data.get("vo2MaxValue"),
                "vo2max_precise": data.get("vo2MaxPreciseValue"),
                "maxmet_category": data.get("maxMetCategory") or data.get("maxmetCategory"),
            }
        )
    monthly = bundle.get("connectapi", {}).get("multi_day", {}).get("monthly_vo2max") or []
    return {"daily": daily, "monthly": monthly}


def _weight_aggregates(bundle: dict) -> List[dict]:
    per_day = bundle.get("connectapi", {}).get("per_day", {}) or {}
    agg = []
    for cal, payloads in per_day.items():
        data = payloads.get("weight_range") or []
        weights = data if isinstance(data, list) else [data]
        for w in weights:
            agg.append(
                {
                    "calendar_date": cal,
                    "weight": w.get("weight"),
                    "bmi": w.get("bmi"),
                    "body_fat": w.get("bodyFat"),
                }
            )
    return agg


def build_aggregate_summary(bundle: dict) -> Dict[str, Any]:
    """
    Build a concise JSON-friendly summary for storing in Postgres (e.g., IngestRun.summary).
    """
    activities = bundle.get("connectapi", {}).get("multi_day", {}).get("activities")
    activities_count = len(activities.get("results", [])) if isinstance(activities, dict) and activities.get("results") else (len(activities) if isinstance(activities, list) else 0)
    return {
        "sleep": _sleep_aggregates(bundle),
        "hrv": _hrv_aggregates(bundle),
        "vo2": _vo2_aggregates(bundle),
        "weight": _weight_aggregates(bundle),
        "steps": _safe_list(bundle, "steps"),
        "stress": _safe_list(bundle, "stress"),
        "intensity_minutes": _safe_list(bundle, "intensity_minutes"),
        "activities": activities_count,
    }
