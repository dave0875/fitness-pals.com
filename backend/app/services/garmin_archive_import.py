"""Normalize supported Garmin archive objects into canonical activities."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from app.services import dedupe
from app.services.garmin.activity import persist_activity_summaries
from app.services.garmin.fit_sdk import decode_fit_bytes, normalized_developer_fields
from app.services.google_drive_archive import DriveArchiveObject

MAX_STRUCTURE_ITEMS = 500


class NoSupportedGarminActivities(ValueError):
    """The object is valid archive material but contains no importable activities."""


def _milliseconds_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _summarized_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        direct = payload.get("summarizedActivitiesExport")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, dict)]
        items: list[dict[str, Any]] = []
        for value in payload.values():
            items.extend(_summarized_items(value))
        return items
    if isinstance(payload, list):
        items = []
        for value in payload:
            items.extend(_summarized_items(value))
        return items
    return []


def _normalize_summary(item: dict[str, Any]) -> dict[str, Any]:
    raw_distance = item.get("distance")
    raw_duration = item.get("duration")
    distance_cm = float(raw_distance) if raw_distance not in (None, "") else None
    duration_ms = float(raw_duration) if raw_duration not in (None, "") else None
    return {
        "activityId": item.get("activityId"),
        "activityName": item.get("name") or item.get("activityName"),
        "activityType": item.get("sportType") or item.get("activityType"),
        "startTimeGmt": _milliseconds_to_iso(
            item.get("startTimeGmt") or item.get("beginTimestamp")
        ),
        "distance": distance_cm / 100 if distance_cm is not None else None,
        "duration": duration_ms / 1000 if duration_ms is not None else None,
        "providerUserId": item.get("userProfileId"),
    }


def _fit_value(message: Any, *names: str) -> Any:
    for name in names:
        value = message.get(name)
        if value is not None:
            return value
    return None


def _fit_number(message: dict[str, Any], *names: str) -> float | None:
    value = _fit_value(message, *names)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fit_time(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _normalized_lap(lap: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "start_time": _fit_time(lap.get("start_time")),
        "timer_seconds": _fit_number(lap, "total_timer_time"),
        "elapsed_seconds": _fit_number(lap, "total_elapsed_time"),
        "distance_m": _fit_number(lap, "total_distance"),
        "avg_heart_rate": _fit_number(lap, "avg_heart_rate"),
        "max_heart_rate": _fit_number(lap, "max_heart_rate"),
        "avg_power": _fit_number(lap, "avg_power"),
        "max_power": _fit_number(lap, "max_power"),
        "avg_cadence": _fit_number(lap, "avg_cadence"),
        "intensity": lap.get("intensity"),
    }


def _normalized_set(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "timestamp": _fit_time(item.get("timestamp")),
        "duration_seconds": _fit_number(item, "duration"),
        "repetitions": _fit_number(item, "repetitions"),
        "weight_kg": _fit_number(item, "weight"),
        "set_type": item.get("set_type"),
        "category": item.get("category") or item.get("exercise_category"),
        "exercise_name": item.get("exercise_name"),
    }


def _fit_activities(content: bytes, source: DriveArchiveObject) -> list[dict[str, Any]]:
    try:
        messages, field_descriptions = decode_fit_bytes(content)
    except ValueError as exc:
        raise ValueError(f"Archive FIT object is not a valid FIT file: {source.name}") from exc
    sessions = messages.get("session_mesgs") or []
    laps = messages.get("lap_mesgs") or []
    sets = messages.get("set_mesgs") or []
    activities: list[dict[str, Any]] = []
    for index, session in enumerate(sessions):
        start = _fit_value(session, "start_time", "timestamp")
        start_value = _fit_time(start)
        provider_sport = str(_fit_value(session, "sport") or "activity")
        raw_sub_sport = _fit_value(session, "sub_sport")
        provider_sub_sport = str(raw_sub_sport) if raw_sub_sport not in (None, "") else None
        first_lap = int(session.get("first_lap_index") or 0)
        num_laps = int(session.get("num_laps") or 0)
        selected_laps = laps[first_lap:first_lap + min(num_laps, MAX_STRUCTURE_ITEMS)] if num_laps else []
        selected_sets = sets[:MAX_STRUCTURE_ITEMS] if len(sessions) == 1 else []
        dev = normalized_developer_fields(session, field_descriptions)

        def value(*names: str) -> Any:
            direct = _fit_value(session, *names)
            if direct is not None:
                return direct
            return _fit_value(dev, *names)

        structure: dict[str, Any] = {}
        if selected_laps:
            structure["laps"] = [_normalized_lap(lap, lap_index) for lap_index, lap in enumerate(selected_laps)]
        if selected_sets:
            structure["sets"] = [_normalized_set(set_item, set_index) for set_index, set_item in enumerate(selected_sets)]

        activities.append(
            {
                "activityId": f"drive:{source.object_id}:{index}",
                "activityName": provider_sub_sport or provider_sport,
                "activityType": provider_sport,
                "subSport": provider_sub_sport,
                "startTimeGmt": start_value,
                "distance": _fit_value(session, "total_distance"),
                "duration": _fit_value(session, "total_timer_time", "total_elapsed_time"),
                "trainingEvidence": {
                    "provider_sport": provider_sport,
                    "provider_sub_sport": provider_sub_sport,
                    "activity_name": provider_sub_sport or provider_sport,
                    "timer_seconds": _fit_number(session, "total_timer_time"),
                    "elapsed_seconds": _fit_number(session, "total_elapsed_time"),
                    "moving_seconds": _fit_number(session, "total_moving_time"),
                    "avg_heart_rate": value("avg_heart_rate", "average_heart_rate"),
                    "max_heart_rate": value("max_heart_rate"),
                    "calories": value("total_calories"),
                    "avg_power": value("avg_power"),
                    "max_power": value("max_power"),
                    "normalized_power": value("normalized_power"),
                    "avg_cadence": value("avg_cadence"),
                    "max_cadence": value("max_cadence"),
                    "aerobic_training_effect": value("total_training_effect", "training_effect"),
                    "anaerobic_training_effect": value("total_anaerobic_training_effect", "anaerobic_training_effect"),
                    "structure": structure or None,
                },
            }
        )
    return activities


def _json_activities(content: bytes) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8-sig"))
    return [_normalize_summary(item) for item in _summarized_items(payload)]


def _archive_activities(content: bytes, source: DriveArchiveObject) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if lowered.endswith("_summarizedactivities.json"):
                activities.extend(_json_activities(archive.read(name)))
            elif lowered.endswith(".fit"):
                nested_source = DriveArchiveObject(
                    object_id=f"{source.object_id}:{name}",
                    name=name,
                    mime_type="application/fits",
                    version=source.version,
                    modified_time=source.modified_time,
                    size_bytes=0,
                )
                activities.extend(_fit_activities(archive.read(name), nested_source))
    return activities


def _object_activities(content: bytes, source: DriveArchiveObject) -> list[dict[str, Any]]:
    lowered = source.name.lower()
    if lowered.endswith(".zip") or source.mime_type == "application/zip":
        return _archive_activities(content, source)
    if lowered.endswith(".fit") or source.mime_type == "application/fits":
        return _fit_activities(content, source)
    if lowered.endswith(".json"):
        return _json_activities(content)
    return []


def ingest_archive_object(*, db, user, source_object: DriveArchiveObject, content: bytes) -> dict:
    """Ingest one checkpointable object with athlete-bound provenance."""
    if not content:
        raise ValueError(f"Archive object is empty: {source_object.name}")
    activities = _object_activities(content, source_object)
    if not activities:
        raise NoSupportedGarminActivities(
            f"Archive object has no supported Garmin activities: {source_object.name}"
        )
    content_hash = hashlib.sha256(content).hexdigest()
    for activity in activities:
        start_time = activity.get("startTimeGmt")
        if start_time:
            activity["canonicalFingerprint"] = dedupe.fingerprint_activity(
                str(start_time),
                activity.get("duration"),
                activity.get("distance"),
                str(activity.get("activityType") or activity.get("activityName") or "activity"),
            )
        activity.update(
            {
                "sourceObjectId": source_object.object_id,
                "sourceObjectName": source_object.name,
                "sourceObjectVersion": source_object.version,
                "sourceContentHash": content_hash,
                "sourceModifiedTime": source_object.modified_time,
            }
        )
    run = dedupe.record_ingest_run(db, provider="garmin_archive", user_id=user.id)
    try:
        persist_activity_summaries(
            db,
            user,
            run,
            activities,
            provider="garmin_archive",
        )
        dedupe.finish_ingest_run(
            db,
            run,
            "completed",
            summary={
                "source_object_id": source_object.object_id,
                "source_version": source_object.version,
                "activity_count": len(activities),
            },
        )
    except Exception:
        dedupe.finish_ingest_run(
            db,
            run,
            "failed",
            summary={"source_object_id": source_object.object_id},
        )
        raise
    return {
        "activity_count": len(activities),
        "ingest_run_id": str(run.id),
        "content_hash": content_hash,
    }
