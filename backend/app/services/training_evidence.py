"""Provider-neutral canonical whole-training evidence."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.models import Activity, ActivityTrainingEvidence

FRESHNESS_WINDOW = timedelta(hours=72)

MODALITY_ALIASES = {
    "running": {"run", "running", "treadmill_running", "trail_running", "track_running", "indoor_running"},
    "cycling": {"bike", "biking", "cycling", "indoor_cycling", "mountain_biking", "road_biking"},
    "walking_hiking": {"walk", "walking", "hike", "hiking"},
    "strength": {"strength", "strength_training", "weight_training"},
    "swimming": {"swim", "swimming", "lap_swimming", "open_water"},
    "rowing": {"row", "rowing", "indoor_rowing"},
    "indoor_cardio": {"elliptical", "stair_climbing", "cardio_training", "hiit", "fitness_equipment"},
    "multisport": {"multisport", "triathlon", "transition"},
}
PRODUCT_FILTERS = {
    "run": "running", "bike": "cycling", "walk": "walking_hiking",
    "strength": "strength", "swim": "swimming", "row": "rowing",
    "cardio": "indoor_cardio",
}


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower().replace(" ", "_")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def sport_family(sport: str | None, sub_sport: str | None = None) -> str:
    """Map provider sport labels to one product modality without guessing running."""
    candidates = [_text(sub_sport), _text(sport)]
    for family, aliases in MODALITY_ALIASES.items():
        if any(candidate in aliases for candidate in candidates if candidate):
            return family
    return "other"


def sport_matches(sport: str | None, selected: str, sub_sport: str | None = None) -> bool:
    if selected == "all":
        return True
    wanted = PRODUCT_FILTERS.get(selected, selected)
    return sport_family(sport, sub_sport) == wanted


def _first(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    return None


def normalize_training_evidence(item: dict[str, Any], provider: str) -> dict[str, Any]:
    """Normalize allow-listed workout evidence; never copy a raw provider payload."""
    supplied = item.get("trainingEvidence")
    supplied = supplied if isinstance(supplied, dict) else {}
    provider_sport = _text(supplied.get("provider_sport") or item.get("activityType"))
    provider_sub_sport = _text(supplied.get("provider_sub_sport") or item.get("subSport"))
    values = {
        "modality": sport_family(provider_sport, provider_sub_sport),
        "provider_sport": provider_sport,
        "provider_sub_sport": provider_sub_sport,
        "activity_name": supplied.get("activity_name") or item.get("activityName"),
        "timer_seconds": _number(supplied.get("timer_seconds") if "timer_seconds" in supplied else _first(item, "duration", "durationSeconds")),
        "elapsed_seconds": _number(supplied.get("elapsed_seconds") if "elapsed_seconds" in supplied else item.get("elapsedDuration")),
        "moving_seconds": _number(supplied.get("moving_seconds")),
        "avg_heart_rate": _number(supplied.get("avg_heart_rate") if "avg_heart_rate" in supplied else _first(item, "averageHR", "averageHeartRate", "avgHR")),
        "max_heart_rate": _number(supplied.get("max_heart_rate") if "max_heart_rate" in supplied else _first(item, "maxHR", "maxHeartRate")),
        "calories": _number(supplied.get("calories") if "calories" in supplied else _first(item, "calories", "activeKilocalories")),
        "avg_power": _number(supplied.get("avg_power") if "avg_power" in supplied else _first(item, "avgPower", "averagePower")),
        "max_power": _number(supplied.get("max_power") if "max_power" in supplied else _first(item, "maxPower")),
        "normalized_power": _number(supplied.get("normalized_power") if "normalized_power" in supplied else _first(item, "normalizedPower")),
        "avg_cadence": _number(supplied.get("avg_cadence") if "avg_cadence" in supplied else _first(item, "averageCadence", "avgCadence")),
        "max_cadence": _number(supplied.get("max_cadence") if "max_cadence" in supplied else _first(item, "maxCadence")),
        "aerobic_training_effect": _number(supplied.get("aerobic_training_effect")),
        "anaerobic_training_effect": _number(supplied.get("anaerobic_training_effect")),
        "structure_json": supplied.get("structure") if isinstance(supplied.get("structure"), dict) else None,
        "source_provider": provider,
        "source_object_id": item.get("sourceObjectId"),
        "source_object_name": item.get("sourceObjectName"),
        "source_object_version": item.get("sourceObjectVersion"),
        "source_content_hash": item.get("sourceContentHash"),
    }
    observed = [
        key for key, value in values.items()
        if key not in {"modality", "source_provider"} and value not in (None, {}, [])
    ]
    values["observed_fields"] = observed
    values["derived_fields"] = ["modality"]
    return values


def persist_training_evidence(db, activity: Activity, run, item: dict[str, Any], provider: str, now: datetime) -> ActivityTrainingEvidence:
    """Upsert richer evidence onto the canonical Activity without changing its identity."""
    normalized = normalize_training_evidence(item, provider)
    try:
        row = (
            db.query(ActivityTrainingEvidence)
            .filter(ActivityTrainingEvidence.activity_id == activity.id)
            .first()
        )
    except Exception:
        row = next(
            (candidate for candidate in getattr(db, "items", [])
             if isinstance(candidate, ActivityTrainingEvidence) and candidate.activity_id == activity.id),
            None,
        )
    if row is None:
        row = ActivityTrainingEvidence(activity_id=activity.id, ingest_run_id=run.id, **normalized)
        db.add(row)
    else:
        row.ingest_run_id = run.id
        for key, value in normalized.items():
            if value not in (None, {}, []):
                setattr(row, key, value)
        row.updated_at = now
    db.commit()
    try:
        db.refresh(row)
    except Exception:
        pass
    return row


def evidence_map(db, activities: list[Activity]) -> dict[Any, ActivityTrainingEvidence]:
    ids = {activity.id for activity in activities}
    if not ids:
        return {}
    try:
        rows = db.query(ActivityTrainingEvidence).filter(
            ActivityTrainingEvidence.activity_id.in_(ids)
        ).all()
    except Exception:
        rows = [
            row for row in getattr(db, "items", [])
            if isinstance(row, ActivityTrainingEvidence)
        ]
    return {row.activity_id: row for row in rows if row.activity_id in ids}


def evidence_payload(activity: Activity, row: ActivityTrainingEvidence | None) -> dict[str, Any]:
    modality = row.modality if row is not None else sport_family(activity.sport)
    payload = {
        "modality": modality,
        "provider_sport": row.provider_sport if row else activity.sport,
        "provider_sub_sport": row.provider_sub_sport if row else None,
        "avg_heart_rate": row.avg_heart_rate if row else None,
        "max_heart_rate": row.max_heart_rate if row else None,
        "calories": row.calories if row else None,
        "avg_power": row.avg_power if row else None,
        "max_power": row.max_power if row else None,
        "normalized_power": row.normalized_power if row else None,
        "avg_cadence": row.avg_cadence if row else None,
        "aerobic_training_effect": row.aerobic_training_effect if row else None,
        "anaerobic_training_effect": row.anaerobic_training_effect if row else None,
        "structure": row.structure_json if row else None,
    }
    return payload


def summarize_activities(activities: list[Activity], rows: dict[Any, ActivityTrainingEvidence]) -> dict[str, Any]:
    """Return unit-safe modality totals. Missing duration remains explicitly missing."""
    by_modality: dict[str, dict[str, Any]] = {}
    hr_duration = 0
    power_duration = 0
    hr_count = 0
    power_count = 0
    strength_count = 0
    cross_count = 0
    for activity in activities:
        row = rows.get(activity.id)
        modality = row.modality if row else sport_family(activity.sport)
        bucket = by_modality.setdefault(modality, {"activity_count": 0, "duration_seconds": 0, "known_duration_count": 0})
        bucket["activity_count"] += 1
        duration = activity.duration_seconds
        if duration is not None:
            bucket["duration_seconds"] += int(duration)
            bucket["known_duration_count"] += 1
        if modality != "running":
            cross_count += 1
        if modality == "strength":
            strength_count += 1
        if row and (row.avg_heart_rate is not None or row.max_heart_rate is not None):
            hr_count += 1
            if duration is not None:
                hr_duration += int(duration)
        if row and modality == "cycling" and (
            row.avg_power is not None or row.max_power is not None or row.normalized_power is not None
        ):
            power_count += 1
            if duration is not None:
                power_duration += int(duration)
    normalized = []
    for modality in sorted(by_modality):
        bucket = by_modality[modality]
        normalized.append({
            "modality": modality,
            "activity_count": bucket["activity_count"],
            "duration_seconds": bucket["duration_seconds"] if bucket["known_duration_count"] else None,
            "known_duration_count": bucket["known_duration_count"],
        })
    durations = [int(a.duration_seconds) for a in activities if a.duration_seconds is not None]
    return {
        "activity_count": len(activities),
        "duration_seconds": sum(durations) if durations else None,
        "known_duration_count": len(durations),
        "by_modality": normalized,
        "cross_training_sessions": cross_count,
        "strength_sessions": strength_count,
        "hr_supported_workouts": hr_count,
        "hr_supported_duration_seconds": hr_duration if hr_count else None,
        "power_supported_cycling_workouts": power_count,
        "power_supported_cycling_duration_seconds": power_duration if power_count else None,
    }


def build_whole_training_summary(db, user_id: UUID, *, now: datetime | None = None, days: int = 30) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=max(1, min(days, 365)))
    try:
        activities = [
            activity for activity in db.query(Activity).filter(Activity.user_id == user_id).all()
            if getattr(activity, "user_id", None) == user_id
            and getattr(activity, "status", None) != "conflict"
            and activity.start_time is not None
            and (activity.start_time if activity.start_time.tzinfo else activity.start_time.replace(tzinfo=timezone.utc)) >= cutoff
        ]
    except Exception:
        return {"state": "error", "data_through": None, "window_days": days, **summarize_activities([], {})}
    activities.sort(key=lambda a: a.start_time, reverse=True)
    rows = evidence_map(db, activities)
    result = summarize_activities(activities, rows)
    latest = activities[0].start_time if activities else None
    if latest is not None and latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    state = "unknown" if latest is None else ("stale" if current - latest > FRESHNESS_WINDOW else "fresh")
    return {
        "state": state,
        "data_through": latest.astimezone(timezone.utc).isoformat() if latest else None,
        "window_days": days,
        **result,
    }
