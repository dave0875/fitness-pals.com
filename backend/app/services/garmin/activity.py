"""Garmin activity helpers: fetch list, details, and write Influx/Postgres."""
# mypy: ignore-errors

from __future__ import annotations

import logging
from datetime import datetime, timezone
import os
from uuid import uuid4
from typing import Optional, List, Dict, Any, cast

from fastapi import HTTPException

from app.models import IngestRun, Activity, ActivitySource
from app.services.garmin import activity_fit
from app.services.garmin import garmin_fit_download
from app.types import CurrentUserLike, InfluxClientLike

logger = logging.getLogger("garmin.activity")
logger.setLevel(logging.INFO)


def _sanitize_influx_field_value(value: Any) -> Any:
    """Normalize field values to types supported by the Influx client."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return None


def _infer_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """Keep scalar fields only to keep Influx points small."""
    fields: Dict[str, Any] = {}
    for k, v in item.items():
        if k in ("time", "startTimeGmt", "startTimeGMT", "startTimeLocal"):
            continue
        if isinstance(v, (int, float, str)) or v is None:
            fields[k] = v
    return fields


def _normalize_activity_list(raw: Any) -> list[Dict[str, Any]]:
    if isinstance(raw, dict) and "activityList" in raw:
        return raw.get("activityList") or []
    if isinstance(raw, list):
        return raw
    return []


def _parse_start_time(val) -> Optional[datetime]:
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    return None


def _trim_activity_metadata(
    item: Dict[str, Any],
    provider_activity_id: str,
    *,
    test_run: bool = False,
) -> Dict[str, Any]:
    """Build compact canonical metadata without copying the raw provider payload."""
    metadata: Dict[str, Any] = {"provider_activity_id": provider_activity_id}
    for source_key, target_key in (
        ("activityName", "activity_name"),
        ("activityType", "activity_type"),
        ("startTimeGMT", "start_time_gmt"),
        ("startTimeGmt", "start_time_gmt"),
        ("startTimeUTC", "start_time_utc"),
        ("startTimeLocal", "start_time_local"),
        ("ownerId", "provider_user_id"),
        ("userProfileId", "provider_user_id"),
        ("username", "provider_username"),
    ):
        value = item.get(source_key)
        if value not in (None, "") and target_key not in metadata:
            metadata[target_key] = value

    for key in (
        "averageRunningCadenceInStepsPerMinute",
        "averageCadence",
        "avgCadence",
        "averageRunCadence",
        "avgRunCadence",
    ):
        if item.get(key) is not None:
            metadata["average_cadence_spm"] = item.get(key)
            break
    for key in (
        "maxRunningCadenceInStepsPerMinute",
        "maxCadence",
        "maxDoubleCadence",
    ):
        if item.get(key) is not None:
            metadata["max_cadence_spm"] = item.get(key)
            break

    for source_key, target_key in (
        ("totalElevationGain", "elevation_gain"),
        ("elevationGain", "elevation_gain"),
        ("elevationLoss", "elevation_loss"),
        ("minElevation", "elevation_min"),
        ("maxElevation", "elevation_max"),
    ):
        value = item.get(source_key)
        if value is not None and target_key not in metadata:
            metadata[target_key] = value

    if test_run:
        metadata["test_run"] = True
    return metadata


def _find_existing_activity(db, user_id: Any, fingerprint: str) -> Optional[Activity]:
    """Return the existing canonical activity for this user/fingerprint if present."""
    try:
        return (
            db.query(Activity)
            .filter(
                Activity.user_id == user_id, Activity.fingerprint_hash == fingerprint
            )
            .first()
        )
    except Exception:
        pass
    for item in getattr(db, "items", []):
        if (
            isinstance(item, Activity)
            and item.user_id == user_id
            and item.fingerprint_hash == fingerprint
        ):
            return item
    return None


def _find_existing_activity_source(
    db,
    activity_id: Any,
    *,
    provider: str,
    provider_activity_id: str,
) -> Optional[ActivitySource]:
    """Return an existing provenance row for this provider activity if present."""
    try:
        return (
            db.query(ActivitySource)
            .filter(
                ActivitySource.activity_id == activity_id,
                ActivitySource.provider == provider,
                ActivitySource.provider_activity_id == provider_activity_id,
            )
            .first()
        )
    except Exception:
        pass
    for item in getattr(db, "items", []):
        if (
            isinstance(item, ActivitySource)
            and item.activity_id == activity_id
            and item.provider == provider
            and item.provider_activity_id == provider_activity_id
        ):
            return item
    return None


def get_latest_activity_start_time(db, user: CurrentUserLike) -> Optional[datetime]:
    """Return most recent start_time stored for this user."""
    try:
        from app.models import Activity as ActivityModel
    except Exception:
        return None
    try:
        rec = (
            db.query(ActivityModel)
            .filter(ActivityModel.user_id == user.id)
            .order_by(ActivityModel.start_time.desc())
            .first()
        )
        return rec.start_time if rec else None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "failed to fetch latest activity start_time",
            extra={"error": str(exc), "user_id": str(getattr(user, "id", ""))},
            exc_info=True,
        )
        return None


def fetch_activity_list(
    client: Any,
    user: CurrentUserLike,
    mode: str,
    provider_key: str,
    test_run: bool,
    since_start_time: Optional[datetime] = None,
    page_limit: int = 20,
    max_pages: Optional[int] = None,
) -> list[Dict[str, Any]]:
    try:
        if max_pages is None:
            try:
                max_pages = int(os.environ.get("GARMIN_MAX_PAGES", "10"))
            except Exception:
                max_pages = 10
        results: list[Dict[str, Any]] = []
        start = 0
        pages = 0
        keep_going = True
        while keep_going and (max_pages is None or pages < max_pages):
            logger.info(
                "garmin activity list fetch",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "mode": mode,
                    "path": "activitylist-service/activities",
                    "test_run": test_run,
                    "start": start,
                    "limit": page_limit,
                    "since": since_start_time.isoformat() if since_start_time else None,
                    "max_pages": max_pages,
                },
            )
            raw = client.connectapi(
                "activitylist-service/activities",
                params={"start": start, "limit": page_limit},
            )
            page_items = _normalize_activity_list(raw)
            if not page_items:
                break
            logger.info(
                "garmin activity page",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "page": pages + 1,
                    "fetched": len(page_items),
                    "total_so_far": len(results) + len(page_items),
                    "test_run": test_run,
                },
            )
            for item in page_items:
                st = _parse_start_time(
                    item.get("startTimeGMT")
                    or item.get("startTimeGmt")
                    or item.get("startTimeUTC")
                )
                if since_start_time and st:
                    sst = (
                        since_start_time
                        if since_start_time.tzinfo
                        else since_start_time.replace(tzinfo=timezone.utc)
                    )
                    st_cmp = st if st.tzinfo else st.replace(tzinfo=timezone.utc)
                    if st_cmp <= sst:
                        keep_going = False
                        break
                    # Reached already ingested range; stop paging
                results.append(item)
            start += page_limit
            pages += 1
            if len(page_items) < page_limit:
                break
        logger.info(
            "garmin activity list complete",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "mode": mode,
                "total_fetched": len(results),
                "pages": pages,
                "test_run": test_run,
            },
        )
        return results
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "garmin activity list fetch failed",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "mode": mode,
                "provider": provider_key,
                "error": str(exc),
                "test_run": test_run,
            },
            exc_info=True,
        )
        raise (
            HTTPException(status_code=410, detail="Garmin reauth required")
            if mode == "scraper"
            else HTTPException(status_code=502, detail="Garmin fetch failed")
        )


def persist_activity_summaries(
    db,
    user: CurrentUserLike,
    run: IngestRun,
    activities: list[dict],
    *,
    test_run: bool = False,
) -> None:
    """Persist basic activity rows in Postgres with ingest linkage."""
    if not activities:
        return
    now = datetime.utcnow()
    for item in activities:
        act_id = item.get("id") or item.get("activityId")
        if act_id is None:
            continue
        provider_activity_id = str(act_id)
        meta = _trim_activity_metadata(item, provider_activity_id, test_run=test_run)
        start_time = (
            item.get("startTimeUTC")
            or item.get("startTimeGmt")
            or item.get("startTimeGMT")
        )
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except Exception:
                start_time = None
        distance_m = None
        for key in ("distance", "distance_m", "totalDistance"):
            if key in item and item.get(key) is not None:
                try:
                    distance_m = float(cast(Any, item.get(key)))
                except Exception:
                    distance_m = None
                break
        duration_s = None
        for key in ("duration", "elapsedDuration", "durationSeconds"):
            if key in item and item.get(key) is not None:
                try:
                    duration_s = float(cast(Any, item.get(key)))
                except Exception:
                    duration_s = None
                break
        fingerprint = provider_activity_id
        activity = _find_existing_activity(db, user.id, fingerprint)
        if activity is None:
            activity = Activity(
                id=uuid4(),
                user_id=user.id,
                ingest_run_id=run.id,
                start_time=start_time or now,
                duration_seconds=int(duration_s) if duration_s is not None else None,
                distance_m=distance_m,
                sport=item.get("activityName") or item.get("activityType") or None,
                status="completed",
                fingerprint_hash=fingerprint,
                metadata_json=meta,
                created_at=now,
                updated_at=now,
            )
            db.add(activity)
            db.commit()
            db.refresh(activity)
        else:
            activity.ingest_run_id = run.id  # type: ignore[assignment]
            activity.updated_at = now  # type: ignore[assignment]
            if activity.metadata_json is None:
                activity.metadata_json = meta  # type: ignore[assignment]

        source = _find_existing_activity_source(
            db,
            activity.id,
            provider="garmin",
            provider_activity_id=provider_activity_id,
        )
        if source is not None:
            continue
        db.add(
            ActivitySource(
                id=uuid4(),
                activity_id=activity.id,
                provider="garmin",
                provider_activity_id=provider_activity_id,
                raw_hash=fingerprint,
                decision="new",
                chosen_fields=meta,
                raw_payload=meta,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def write_activity_summary_influx(
    db,
    user: CurrentUserLike,
    run: IngestRun,
    influx_client: InfluxClientLike | None,
    ingest_run_tag: str,
    activities: list[dict],
) -> int:
    if not influx_client or not activities:
        return 0
    points = []
    tags = {
        "user_id": str(getattr(user, "id", "")),
        "ingest_run_id": ingest_run_tag,
        "provider": "garmin",
    }
    for act in activities:
        start_time = (
            act.get("startTimeGMT")
            or act.get("startTimeGmt")
            or act.get("startTimeLocal")
        )
        fields = _infer_fields(act)
        if not fields:
            continue
        points.append(
            {
                "measurement": "ActivitySummary",
                "time": start_time,
                "tags": tags,
                "fields": fields,
            }
        )
    if not points:
        return 0
    influx_client.write_api().write(
        bucket=influx_client.default_bucket, org=influx_client.org, record=points
    )
    return len(points)


def fetch_activity_details(
    client: Any,
    activity_id: Any,
    user: CurrentUserLike,
    provider_key: str,
    test_run: bool,
) -> Optional[Dict[str, Any]]:
    path = f"activity-service/activity/{activity_id}/details"
    params = {"maxChartSize": 5000, "maxPolylineSize": 5000}
    try:
        logger.info(
            "garmin activity details fetch",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "provider": provider_key,
                "activity_id": activity_id,
                "path": path,
                "test_run": test_run,
            },
        )
        return client.connectapi(path, params=params)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "garmin activity details fetch failed",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "provider": provider_key,
                "activity_id": activity_id,
                "path": path,
                "error": str(exc),
                "test_run": test_run,
            },
            exc_info=True,
        )
        return None


def _to_ns(
    ts, start_epoch_ns: Optional[int], duration_seconds: Optional[float]
) -> Optional[int]:
    if ts is None:
        return None
    try:
        val = float(ts)
    except Exception:
        return None
    if val > 1e15:
        return int(val)
    if val > 1e12:
        return int(val * 1_000_000)  # ms -> ns
    if val > 1e9:
        return int(val * 1000)  # µs -> ns
    return int(val * 1_000_000_000)  # seconds -> ns


def parse_activity_gps_samples(
    detail: Any,
    activity_id: Any,
    activity_name: Optional[str],
    start_time: Optional[datetime],
) -> list[Dict[str, Any]]:
    """Extract per-sample GPS/metric points mapped to ActivityGPS schema from JSON detail."""
    if not detail:
        return []
    detail_dict = detail if isinstance(detail, dict) else {}
    samples: list[Dict[str, Any]] = []
    start_epoch_ns = int(start_time.timestamp() * 1_000_000_000) if start_time else None

    # Prefer metricDescriptors + activityDetailMetrics shape
    descriptors = detail_dict.get("metricDescriptors")
    metrics = detail_dict.get("activityDetailMetrics")
    if isinstance(descriptors, list) and isinstance(metrics, list):
        idx_to_desc = {
            d.get("metricsIndex"): d for d in descriptors if isinstance(d, dict)
        }
        key_map = {
            "sumDistance": "Distance",
            "sumDuration": "DurationSeconds",
            "sumMovingDuration": "DurationSeconds",
            "sumElapsedDuration": "DurationSeconds",
            "directElevation": "Altitude",
            "directSpeed": "Speed",
            "directHeartRate": "HeartRate",
            "directRunCadence": "Cadence",
            "directDoubleCadence": "Cadence",
            "directFractionalCadence": "Fractional_Cadence",
            "directVerticalOscillation": "Vertical_Oscillation",
            "directGroundContactTime": "Ground_Contact_Time",
            "directVerticalRatio": "Vertical_Ratio",
            "directAirTemperature": "Temperature",
            "directStrideLength": "StrideLength",
            "directGradeAdjustedSpeed": "GradeAdjustedSpeed",
            "directPerformanceCondition": "PerformanceCondition",
            "directLatitude": "Latitude",
            "directLongitude": "Longitude",
        }
        ts_idx = None
        for idx, desc in idx_to_desc.items():
            if desc.get("key") == "directTimestamp":
                ts_idx = idx
                break
        for entry in metrics:
            if not isinstance(entry, dict):
                continue
            vals = entry.get("metrics") or []
            fields: Dict[str, Any] = {}
            for idx, desc in idx_to_desc.items():
                if idx is None or idx >= len(vals):
                    continue
                val = vals[idx]
                if val is None:
                    continue
                key_val = desc.get("key")
                if not isinstance(key_val, str):
                    continue
                target_field = key_map.get(key_val)
                if not target_field:
                    continue
                factor = desc.get("unit", {}).get("factor", 1.0) or 1.0
                try:
                    fields[target_field] = float(val) / float(factor)
                except Exception:
                    fields[target_field] = val
            if "Cadence" in fields and fields.get("Cadence") is not None:
                try:
                    fields["Cadence"] = int(round(float(fields["Cadence"])))
                except Exception:
                    pass
            if "Temperature" in fields and fields.get("Temperature") is not None:
                try:
                    fields["Temperature"] = int(round(float(fields["Temperature"])))
                except Exception:
                    pass
            ts_val = vals[ts_idx] if ts_idx is not None and ts_idx < len(vals) else None
            ts_ns = _to_ns(ts_val, start_epoch_ns, fields.get("DurationSeconds"))
            if ts_ns is None and "DurationSeconds" in fields and start_epoch_ns:
                try:
                    ts_ns = start_epoch_ns + int(
                        float(fields["DurationSeconds"]) * 1_000_000_000
                    )
                except Exception:
                    ts_ns = start_epoch_ns
            if activity_id:
                fields.setdefault("ActivityID", activity_id)
            if activity_name:
                fields.setdefault("ActivityName", activity_name)
            samples.append(
                {
                    "time": ts_ns,
                    "fields": {k: v for k, v in fields.items() if v is not None},
                }
            )
        return [s for s in samples if s.get("fields")]

    # Fallback: other generic shapes
    candidates: List[List[Dict[str, Any]]] = []
    for key in ("samples", "metrics", "laps", "geoPoints", "points"):
        val = detail_dict.get(key)
        if isinstance(val, list):
            candidates.append(val)  # type: ignore[arg-type]
    if not candidates and isinstance(detail, list):
        candidates.append(detail)
    if not candidates:
        return []

    for arr in candidates:
        for item in arr:
            if not isinstance(item, dict):
                continue
            fields: Dict[str, Any] = {}
            if "accumulatedPower" in item:
                fields["Accumulated_Power"] = item.get("accumulatedPower")
            if "altitude" in item:
                fields["Altitude"] = item.get("altitude")
            if "elevation" in item:
                fields["Altitude"] = item.get("elevation")
            if "cadence" in item:
                try:
                    fields["Cadence"] = int(
                        round(float(cast(Any, item.get("cadence"))))
                    )
                except Exception:
                    fields["Cadence"] = item.get("cadence")
            if "fractionalCadence" in item:
                fields["Fractional_Cadence"] = item.get("fractionalCadence")
            if "distance" in item:
                fields["Distance"] = item.get("distance")
            if "duration" in item:
                fields["DurationSeconds"] = item.get("duration")
            if "speed" in item:
                fields["Speed"] = item.get("speed")
            if "gradeAdjustedSpeed" in item:
                fields["GradeAdjustedSpeed"] = item.get("gradeAdjustedSpeed")
            if "groundContactTime" in item:
                fields["Ground_Contact_Time"] = item.get("groundContactTime")
            if "heartRate" in item:
                fields["HeartRate"] = item.get("heartRate")
            if "lat" in item or "latitude" in item:
                fields["Latitude"] = (
                    item.get("lat") if "lat" in item else item.get("latitude")
                )
            if "lon" in item or "longitude" in item:
                fields["Longitude"] = (
                    item.get("lon") if "lon" in item else item.get("longitude")
                )
            if "power" in item:
                fields["Power"] = item.get("power")
            if "runningEfficiency" in item:
                fields["RunningEfficiency"] = item.get("runningEfficiency")
            if "temperature" in item:
                try:
                    fields["Temperature"] = int(
                        round(float(cast(Any, item.get("temperature"))))
                    )
                except Exception:
                    fields["Temperature"] = item.get("temperature")
            if "verticalOscillation" in item:
                fields["Vertical_Oscillation"] = item.get("verticalOscillation")
            if "verticalRatio" in item:
                fields["Vertical_Ratio"] = item.get("verticalRatio")
            if "lapIndex" in item:
                fields["lap"] = item.get("lapIndex")
            if activity_id and "ActivityID" not in fields:
                fields["ActivityID"] = activity_id
            if activity_name:
                fields["ActivityName"] = activity_name
            ts = (
                item.get("timestamp")
                or item.get("startTimestamp")
                or item.get("startTimeInMs")
                or item.get("startTimeInSeconds")
            )
            ts_ns = _to_ns(ts, start_epoch_ns, fields.get("DurationSeconds"))
            if ts_ns is None and "DurationSeconds" in fields and start_epoch_ns:
                try:
                    duration_val = fields.get("DurationSeconds")
                    if duration_val is not None:
                        ts_ns = start_epoch_ns + int(
                            float(cast(Any, duration_val)) * 1_000_000_000
                        )
                    else:
                        ts_ns = start_epoch_ns
                except Exception:
                    ts_ns = start_epoch_ns
            samples.append(
                {
                    "time": ts_ns,
                    "fields": {k: v for k, v in fields.items() if v is not None},
                }
            )
    return [s for s in samples if s.get("fields")]


def merge_gps_and_fit_samples(
    json_samples: list[Dict[str, Any]], fit_samples: list[Dict[str, Any]]
) -> list[Dict[str, Any]]:
    """Merge JSON and FIT samples; FIT overrides on timestamp collisions."""
    merged: Dict[Any, Dict[str, Any]] = {}
    for s in json_samples:
        merged[s.get("time")] = s
    for s in fit_samples:
        merged[s.get("time")] = s
    ordered = list(merged.values())
    ordered.sort(key=lambda x: x.get("time") or 0)
    return ordered


def extract_activity_timeseries(
    client: Any,
    activity_id: Any,
    activity_name: Optional[str],
    start_time: Optional[datetime],
    user: CurrentUserLike,
    provider_key: str,
    test_run: bool,
) -> list[Dict[str, Any]]:
    """
    Fetch and assemble activity timeseries. Prefer FIT (richer data) merged with JSON detail.
    """
    detail = fetch_activity_details(client, activity_id, user, provider_key, test_run)
    json_samples = (
        parse_activity_gps_samples(detail, activity_id, activity_name, start_time)
        if detail
        else []
    )

    fit_samples: list[dict] = []
    fit_flag = os.environ.get("GARMIN_FIT_FILE", "1")
    if fit_flag == "1":
        try:
            fit_bytes = garmin_fit_download.download_fit_file(client, activity_id)
            if fit_bytes:
                fit_samples = activity_fit.parse_fit_file_to_timeseries(
                    fit_bytes, activity_id, activity_name, start_time
                )
        except garmin_fit_download.GarminAuthError as exc:
            logger.warning(
                "activity FIT auth failed",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "provider": provider_key,
                    "activity_id": activity_id,
                    "error": str(exc),
                    "test_run": test_run,
                },
                exc_info=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "activity FIT parse failed",
                extra={
                    "user_id": str(getattr(user, "id", "")),
                    "provider": provider_key,
                    "activity_id": activity_id,
                    "error": str(exc),
                    "test_run": test_run,
                },
                exc_info=True,
            )

    if fit_samples:
        return merge_gps_and_fit_samples(json_samples, fit_samples)
    return json_samples


def write_activity_gps(
    influx_client: InfluxClientLike | None,
    user: CurrentUserLike,
    run: IngestRun,
    ingest_run_tag: str,
    activity_id,
    samples: list[dict],
) -> int:
    """Write ActivityGPS samples using existing schema."""
    if not influx_client or not samples:
        return 0
    points = []
    for sample in samples:
        raw_fields = sample.get("fields") or {}
        fields = {
            key: cleaned
            for key, value in raw_fields.items()
            if (cleaned := _sanitize_influx_field_value(value)) is not None
        }
        if not fields:
            continue
        points.append(
            {
                "measurement": "ActivityGPS",
                "time": sample.get("time"),
                "tags": {
                    "user_id": str(user.id),
                    "ingest_run_id": ingest_run_tag,
                    "provider": "garmin",
                    "activity_id": str(activity_id) if activity_id else None,
                },
                "fields": fields,
            }
        )
    if not points:
        return 0
    write_api = influx_client.write_api()
    write_api.write(
        bucket=influx_client.default_bucket, org=influx_client.org, record=points
    )
    return len(points)
