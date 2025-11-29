"""Garmin activity helpers: fetch list, details, and write Influx/Postgres."""
# mypy: ignore-errors

from __future__ import annotations

import logging
from datetime import datetime, timezone
import os
from typing import Optional, List, Dict

from fastapi import HTTPException

from app.models import IngestRun, Activity
from app.services.garmin import activity_fit
from app.services.garmin import garmin_fit_download

logger = logging.getLogger("garmin.activity")
logger.setLevel(logging.INFO)


def _infer_fields(item: Dict[str, any]) -> Dict[str, any]:
    """Keep scalar fields only to keep Influx points small."""
    fields: Dict[str, any] = {}
    for k, v in item.items():
        if k in ("time", "startTimeGmt", "startTimeGMT", "startTimeLocal"):
            continue
        if isinstance(v, (int, float, str)) or v is None:
            fields[k] = v
    return fields


def _normalize_activity_list(raw) -> list[dict]:
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


def get_latest_activity_start_time(db, user) -> Optional[datetime]:
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
    client,
    user,
    mode: str,
    provider_key: str,
    test_run: bool,
    since_start_time: Optional[datetime] = None,
    page_limit: int = 20,
    max_pages: Optional[int] = None,
) -> list[dict]:
    try:
        if max_pages is None:
            try:
                max_pages = int(os.environ.get("GARMIN_MAX_PAGES", "10"))
            except Exception:
                max_pages = 10
        results: list[dict] = []
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
            raw = client.connectapi("activitylist-service/activities", params={"start": start, "limit": page_limit})
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
                st = _parse_start_time(item.get("startTimeGMT") or item.get("startTimeGmt") or item.get("startTimeUTC"))
                if since_start_time and st:
                    sst = since_start_time if since_start_time.tzinfo else since_start_time.replace(tzinfo=timezone.utc)
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
        raise HTTPException(status_code=410, detail="Garmin reauth required") if mode == "scraper" else HTTPException(status_code=502, detail="Garmin fetch failed")


def persist_activity_summaries(db, user, run: IngestRun, activities: list[dict], *, test_run: bool = False) -> None:
    """Persist basic activity rows in Postgres with ingest linkage."""
    if not activities:
        return
    now = datetime.utcnow()
    created = []
    for item in activities:
        act_id = item.get("id") or item.get("activityId")
        if act_id is None:
            continue
        # Ensure metadata includes provider activity id for traceability
        meta = dict(item) if isinstance(item, dict) else {}
        meta.setdefault("provider_activity_id", act_id)
        # Capture cadence summaries if Garmin provided them
        cadence_keys = (
            "averageRunningCadenceInStepsPerMinute",
            "averageCadence",
            "avgCadence",
            "averageRunCadence",
            "avgRunCadence",
        )
        max_cadence_keys = (
            "maxRunningCadenceInStepsPerMinute",
            "maxCadence",
            "maxDoubleCadence",
        )
        for key in cadence_keys:
            if item.get(key) is not None:
                meta.setdefault("average_cadence_spm", item.get(key))
                break
        for key in max_cadence_keys:
            if item.get(key) is not None:
                meta.setdefault("max_cadence_spm", item.get(key))
                break
        # Capture elevation summaries if provided
        elev_gain = item.get("totalElevationGain") or item.get("elevationGain")
        elev_loss = item.get("elevationLoss")
        elev_min = item.get("minElevation")
        elev_max = item.get("maxElevation")
        if elev_gain is not None:
            meta.setdefault("elevation_gain", elev_gain)
        if elev_loss is not None:
            meta.setdefault("elevation_loss", elev_loss)
        if elev_min is not None:
            meta.setdefault("elevation_min", elev_min)
        if elev_max is not None:
            meta.setdefault("elevation_max", elev_max)
        if test_run:
            meta["test_run"] = True
        start_time = item.get("startTimeUTC") or item.get("startTimeGmt") or item.get("startTimeGMT")
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except Exception:
                start_time = None
        distance_m = None
        for key in ("distance", "distance_m", "totalDistance"):
            if key in item and item.get(key) is not None:
                try:
                    distance_m = float(item.get(key))
                except Exception:
                    distance_m = None
                break
        duration_s = None
        for key in ("duration", "elapsedDuration", "durationSeconds"):
            if key in item and item.get(key) is not None:
                try:
                    duration_s = float(item.get(key))
                except Exception:
                    duration_s = None
                break
        fingerprint = str(act_id)
        activity = Activity(
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
        created.append(activity)
        db.add(activity)
    if created:
        db.commit()


def write_activity_summary_influx(db, user, run: IngestRun, influx_client, ingest_run_tag: str, activities: list[dict]) -> int:
    if not influx_client or not activities:
        return 0
    points = []
    tags = {
        "user_id": str(getattr(user, "id", "")),
        "ingest_run_id": ingest_run_tag,
        "provider": "garmin",
    }
    for act in activities:
        start_time = act.get("startTimeGMT") or act.get("startTimeGmt") or act.get("startTimeLocal")
        fields = _infer_fields(act)
        if not fields:
            continue
        points.append({"measurement": "ActivitySummary", "time": start_time, "tags": tags, "fields": fields})
    if not points:
        return 0
    influx_client.write_api().write(bucket=influx_client.default_bucket, org=influx_client.org, record=points)
    return len(points)


def fetch_activity_details(client, activity_id, user, provider_key: str, test_run: bool) -> Optional[dict]:
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


def _to_ns(ts, start_epoch_ns: Optional[int], duration_seconds: Optional[float]) -> Optional[int]:
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


def parse_activity_gps_samples(detail: dict, activity_id, activity_name: Optional[str], start_time: Optional[datetime]) -> list[dict]:
    """Extract per-sample GPS/metric points mapped to ActivityGPS schema from JSON detail."""
    if not detail or not isinstance(detail, dict):
        return []
    samples = []
    start_epoch_ns = int(start_time.timestamp() * 1_000_000_000) if start_time else None

    # Prefer metricDescriptors + activityDetailMetrics shape
    descriptors = detail.get("metricDescriptors")
    metrics = detail.get("activityDetailMetrics")
    if isinstance(descriptors, list) and isinstance(metrics, list):
        idx_to_desc = {d.get("metricsIndex"): d for d in descriptors if isinstance(d, dict)}
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
            fields = {}
            for idx, desc in idx_to_desc.items():
                if idx is None or idx >= len(vals):
                    continue
                val = vals[idx]
                if val is None:
                    continue
                key = desc.get("key")
                target_field = key_map.get(key)
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
                    ts_ns = start_epoch_ns + int(float(fields["DurationSeconds"]) * 1_000_000_000)
                except Exception:
                    ts_ns = start_epoch_ns
            if activity_id:
                fields.setdefault("ActivityID", activity_id)
            if activity_name:
                fields.setdefault("ActivityName", activity_name)
            samples.append({"time": ts_ns, "fields": {k: v for k, v in fields.items() if v is not None}})
        return [s for s in samples if s.get("fields")]

    # Fallback: other generic shapes
    candidates: List[List[Dict]] = []
    for key in ("samples", "metrics", "laps", "geoPoints", "points"):
        if isinstance(detail.get(key), list):
            candidates.append(detail.get(key))
    if not candidates and isinstance(detail, list):
        candidates.append(detail)
    if not candidates:
        return []

    for arr in candidates:
        for item in arr:
            if not isinstance(item, dict):
                continue
            fields = {}
            if "accumulatedPower" in item:
                fields["Accumulated_Power"] = item.get("accumulatedPower")
            if "altitude" in item:
                fields["Altitude"] = item.get("altitude")
            if "elevation" in item:
                fields["Altitude"] = item.get("elevation")
            if "cadence" in item:
                try:
                    fields["Cadence"] = int(round(float(item.get("cadence"))))
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
                fields["Latitude"] = item.get("lat") if "lat" in item else item.get("latitude")
            if "lon" in item or "longitude" in item:
                fields["Longitude"] = item.get("lon") if "lon" in item else item.get("longitude")
            if "power" in item:
                fields["Power"] = item.get("power")
            if "runningEfficiency" in item:
                fields["RunningEfficiency"] = item.get("runningEfficiency")
            if "temperature" in item:
                try:
                    fields["Temperature"] = int(round(float(item.get("temperature"))))
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
            ts = item.get("timestamp") or item.get("startTimestamp") or item.get("startTimeInMs") or item.get("startTimeInSeconds")
            ts_ns = _to_ns(ts, start_epoch_ns, fields.get("DurationSeconds"))
            if ts_ns is None and "DurationSeconds" in fields and start_epoch_ns:
                try:
                    ts_ns = start_epoch_ns + int(float(fields["DurationSeconds"]) * 1_000_000_000)
                except Exception:
                    ts_ns = start_epoch_ns
            samples.append({"time": ts_ns, "fields": {k: v for k, v in fields.items() if v is not None}})
    return [s for s in samples if s.get("fields")]


def merge_gps_and_fit_samples(json_samples: list[dict], fit_samples: list[dict]) -> list[dict]:
    """Merge JSON and FIT samples; FIT overrides on timestamp collisions."""
    merged: dict = {}
    for s in json_samples:
        merged[s.get("time")] = s
    for s in fit_samples:
        merged[s.get("time")] = s
    ordered = list(merged.values())
    ordered.sort(key=lambda x: x.get("time") or 0)
    return ordered


def extract_activity_timeseries(
    client,
    activity_id,
    activity_name: Optional[str],
    start_time: Optional[datetime],
    user,
    provider_key: str,
    test_run: bool,
) -> list[dict]:
    """
    Fetch and assemble activity timeseries. Prefer FIT (richer data) merged with JSON detail.
    """
    detail = fetch_activity_details(client, activity_id, user, provider_key, test_run)
    json_samples = parse_activity_gps_samples(detail, activity_id, activity_name, start_time) if detail else []

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


def write_activity_gps(influx_client, user, run: IngestRun, ingest_run_tag: str, activity_id, samples: list[dict]) -> int:
    """Write ActivityGPS samples using existing schema."""
    if not influx_client or not samples:
        return 0
    points = []
    for sample in samples:
        fields = sample.get("fields") or {}
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
    write_api.write(bucket=influx_client.default_bucket, org=influx_client.org, record=points)
    return len(points)
