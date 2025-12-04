"""Garmin FIT parsing helpers for activity timeseries."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, cast

import io

from fitparse import FitFile

logger = logging.getLogger("garmin.activity_fit")
logger.setLevel(logging.INFO)

SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)


def _to_ns(dt: Optional[datetime]) -> Optional[int]:
    if not dt:
        return None
    try:
        return int(dt.timestamp() * 1_000_000_000)
    except Exception:
        return None


def _convert_semicircles(val: Any) -> Any:
    try:
        return float(val) * SEMICIRCLE_TO_DEG
    except Exception:
        return val


def _normalize_field_name(name: str) -> str:
    return name.lower().replace(" ", "_")


def fetch_fit_file(client, activity_id) -> Optional[bytes]:
    """Download FIT file bytes for an activity."""
    paths = [
        f"download-service/export/fit/activity/{activity_id}",
        f"download-service/files/activity/{activity_id}",  # zip-wrapped FIT
    ]
    for path in paths:
        try:
            logger.info("garmin fit download", extra={"activity_id": activity_id, "path": path})
            data = client.download(path)
            if not data:
                continue
            # If zip, unwrap to first .fit
            if data.startswith(b"PK\x03\x04"):
                import zipfile, io

                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        fit_name = next((n for n in zf.namelist() if n.lower().endswith(".fit")), None)
                        if fit_name:
                            with zf.open(fit_name) as fh:
                                return fh.read()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "garmin fit unzip failed",
                        extra={"activity_id": activity_id, "path": path, "error": str(exc)},
                        exc_info=True,
                    )
                    continue
            return data
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "garmin fit download failed",
                extra={"activity_id": activity_id, "path": path, "error": str(exc)},
                exc_info=True,
            )
            continue
    return None


def _extract_record_fields(msg) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    for f in msg:
        name = _normalize_field_name(f.name)
        val = f.value
        if name in ("position_lat", "position_long"):
            val = _convert_semicircles(val)
        fields[name] = val
    aliases = {
        "position_lat": "Latitude",
        "position_long": "Longitude",
        "altitude": "Altitude",
        "distance": "Distance",
        "speed": "Speed",
        "heart_rate": "HeartRate",
        "cadence": "Cadence",
        "fractional_cadence": "Fractional_Cadence",
        "power": "Power",
        "vertical_oscillation": "Vertical_Oscillation",
        "stance_time": "StanceTime",
        "stance_time_percent": "StanceTimePercent",
        "ground_contact_time_balance": "GroundContactTimeBalance",
        "vertical_ratio": "Vertical_Ratio",
        "temperature": "Temperature",
        "grade_adjusted_speed": "GradeAdjustedSpeed",
        "stance_time_balance": "StanceTimeBalance",
    }
    normalized = {}
    for k, v in fields.items():
        key = aliases.get(k, None)
        if key:
            normalized[key] = v
        else:
            normalized[k] = v
    if "Cadence" in normalized and normalized.get("Cadence") is not None:
        try:
            normalized["Cadence"] = int(round(float(normalized["Cadence"])))
        except Exception:
            pass
    if "Temperature" in normalized and normalized.get("Temperature") is not None:
        try:
            normalized["Temperature"] = int(round(float(normalized["Temperature"])))
        except Exception:
            pass
    return normalized


def _extract_developer_fields(msg) -> Dict[str, Any]:
    dev_fields: Dict[str, Any] = {}
    for f in getattr(msg, "developer_fields", []):
        try:
            name = _normalize_field_name(f.name)
        except Exception:
            continue
        try:
            val = f.value
        except Exception:
            continue
        if name and val is not None:
            dev_fields[name] = val
    return dev_fields


def parse_fit_file_to_timeseries(fit_bytes: bytes, activity_id, activity_name: Optional[str], start_time: Optional[datetime]) -> List[Dict[str, Any]]:
    """Parse FIT bytes into unified timeseries samples."""
    samples: List[Dict[str, Any]] = []
    try:
        fit = FitFile(io.BytesIO(fit_bytes), data_processor=None)
    except Exception as exc:
        logger.warning("fitparse failed to open FIT", extra={"activity_id": activity_id, "error": str(exc)}, exc_info=True)
        return samples

    last_record_ts_ns: Optional[int] = _to_ns(start_time)

    for msg in fit.get_messages("record"):
        try:
            msg_any = cast(Any, msg)
            ts = msg_any.get_value("timestamp")
            ts_ns = _to_ns(ts) or last_record_ts_ns
            fields = _extract_record_fields(msg_any)
            dev_fields = _extract_developer_fields(msg_any)
            fields.update(dev_fields)
            if activity_id:
                fields["ActivityID"] = activity_id
            if activity_name:
                fields["ActivityName"] = activity_name
            samples.append({"time": ts_ns, "fields": {k: v for k, v in fields.items() if v is not None}})
            if ts_ns is not None:
                last_record_ts_ns = ts_ns
        except Exception:
            continue

    for msg in fit.get_messages("hrv"):
        try:
            msg_any = cast(Any, msg)
            rr_list = msg_any.get_value("time") or []
            if not isinstance(rr_list, list):
                continue
            base_ts_ns = last_record_ts_ns or _to_ns(start_time)
            for rr in rr_list:
                try:
                    rr_ms = float(rr) * 1000.0
                except Exception:
                    continue
                rr_fields: Dict[str, Any] = {"RR": rr_ms}
                if activity_id:
                    rr_fields["ActivityID"] = activity_id
                if activity_name:
                    rr_fields["ActivityName"] = activity_name
                samples.append({"time": base_ts_ns, "fields": rr_fields})
        except Exception:
            continue

    return [s for s in samples if s.get("fields")]


def merge_timeseries(existing_samples: List[Dict[str, Any]], fit_samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge and sort by timestamp; FIT samples override on identical timestamps."""
    merged = {s.get("time"): s for s in existing_samples if s.get("time") is not None}
    for s in fit_samples:
        merged[s.get("time")] = s
    no_time = [s for s in existing_samples + fit_samples if s.get("time") is None]
    out = list(merged.values())
    out.sort(key=lambda x: x.get("time") or 0)
    out.extend(no_time)
    return out


def extract_activity_timeseries(client, activity_id, activity_name: Optional[str], start_time: Optional[datetime]) -> List[Dict[str, Any]]:
    """Fetch FIT file, parse, and return unified timeseries."""
    fit_bytes = fetch_fit_file(client, activity_id)
    if not fit_bytes:
        return []
    return parse_fit_file_to_timeseries(fit_bytes, activity_id, activity_name, start_time)
