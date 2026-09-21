"""Normalize supported Garmin archive objects into canonical activities."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from app.services import dedupe
from app.services.garmin.activity import persist_activity_summaries
from app.services.google_drive_archive import DriveArchiveObject


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
    distance_cm = float(item.get("distance") or 0)
    duration_ms = float(item.get("duration") or 0)
    return {
        "activityId": item.get("activityId"),
        "activityName": item.get("name") or item.get("activityName"),
        "activityType": item.get("sportType") or item.get("activityType"),
        "startTimeGmt": _milliseconds_to_iso(
            item.get("startTimeGmt") or item.get("beginTimestamp")
        ),
        "distance": distance_cm / 100 if distance_cm else 0,
        "duration": duration_ms / 1000 if duration_ms else 0,
        "providerUserId": item.get("userProfileId"),
    }


def _fit_value(message: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = message.get(name)
        if value is not None:
            return value
    return None


def _fit_activities(content: bytes, source: DriveArchiveObject) -> list[dict[str, Any]]:
    stream = Stream.from_byte_io(io.BytesIO(content))
    decoder = Decoder(stream)
    if not decoder.is_fit():
        raise ValueError(f"Archive FIT object is not a valid FIT file: {source.name}")
    messages, errors = decoder.read()
    if errors:
        error = errors[0]
        if isinstance(error, Exception):
            raise error
        raise RuntimeError(str(error))
    sessions = messages.get("session_mesgs") or []
    activities: list[dict[str, Any]] = []
    for index, session in enumerate(sessions):
        start = _fit_value(session, "start_time", "timestamp")
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start_value = start.isoformat()
        else:
            start_value = None
        activities.append(
            {
                "activityId": f"drive:{source.object_id}:{index}",
                "activityName": str(_fit_value(session, "sport", "sub_sport") or "activity"),
                "activityType": str(_fit_value(session, "sport", "sub_sport") or "activity"),
                "startTimeGmt": start_value,
                "distance": _fit_value(session, "total_distance"),
                "duration": _fit_value(
                    session, "total_timer_time", "total_elapsed_time"
                ),
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
