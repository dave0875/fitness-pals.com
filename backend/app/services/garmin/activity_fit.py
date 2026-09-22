"""Garmin FIT parsing helpers for activity timeseries."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Optional

from app.services.garmin.fit_sdk import decode_fit_bytes, normalized_developer_fields

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
            if data.startswith(b"PK\x03\x04"):
                import io
                import zipfile

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


def _extract_record_fields(msg: Mapping[str, Any]) -> dict[str, Any]:
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
    normalized: dict[str, Any] = {}
    for raw_name, raw_value in msg.items():
        if raw_name in {"mesg_num", "developer_fields"}:
            continue
        name = _normalize_field_name(str(raw_name))
        value = raw_value
        if name in ("position_lat", "position_long"):
            value = _convert_semicircles(value)
        normalized[aliases.get(name, name)] = value

    if normalized.get("Cadence") is not None:
        try:
            normalized["Cadence"] = int(round(float(normalized["Cadence"])))
        except Exception:
            pass
    if normalized.get("Temperature") is not None:
        try:
            normalized["Temperature"] = int(round(float(normalized["Temperature"])))
        except Exception:
            pass
    return normalized


def parse_fit_file_to_timeseries(
    fit_bytes: bytes,
    activity_id,
    activity_name: Optional[str],
    start_time: Optional[datetime],
) -> list[dict[str, Any]]:
    """Parse FIT bytes into unified timeseries samples using Garmin's FIT SDK."""
    samples: list[dict[str, Any]] = []
    try:
        messages, field_descriptions = decode_fit_bytes(fit_bytes)
    except Exception as exc:
        logger.warning(
            "Garmin FIT SDK failed to decode FIT",
            extra={"activity_id": activity_id, "error": str(exc)},
            exc_info=True,
        )
        return samples

    last_record_ts_ns: Optional[int] = _to_ns(start_time)

    for message in messages.get("record_mesgs") or []:
        try:
            ts = message.get("timestamp")
            ts_ns = _to_ns(ts if isinstance(ts, datetime) else None) or last_record_ts_ns
            fields = _extract_record_fields(message)
            fields.update(normalized_developer_fields(message, field_descriptions))
            if activity_id:
                fields["ActivityID"] = activity_id
            if activity_name:
                fields["ActivityName"] = activity_name
            samples.append(
                {
                    "time": ts_ns,
                    "fields": {key: value for key, value in fields.items() if value is not None},
                }
            )
            if ts_ns is not None:
                last_record_ts_ns = ts_ns
        except Exception:
            continue

    for message in messages.get("hrv_mesgs") or []:
        try:
            rr_list = message.get("time") or []
            if not isinstance(rr_list, list):
                continue
            base_ts_ns = last_record_ts_ns or _to_ns(start_time)
            for rr in rr_list:
                try:
                    rr_ms = float(rr) * 1000.0
                except Exception:
                    continue
                rr_fields: dict[str, Any] = {"RR": rr_ms}
                if activity_id:
                    rr_fields["ActivityID"] = activity_id
                if activity_name:
                    rr_fields["ActivityName"] = activity_name
                samples.append({"time": base_ts_ns, "fields": rr_fields})
        except Exception:
            continue

    return [sample for sample in samples if sample.get("fields")]


def merge_timeseries(
    existing_samples: list[dict[str, Any]],
    fit_samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge and sort by timestamp; FIT samples override on identical timestamps."""
    merged = {sample.get("time"): sample for sample in existing_samples if sample.get("time") is not None}
    for sample in fit_samples:
        merged[sample.get("time")] = sample
    no_time = [
        sample
        for sample in existing_samples + fit_samples
        if sample.get("time") is None
    ]
    out = list(merged.values())
    out.sort(key=lambda item: item.get("time") or 0)
    out.extend(no_time)
    return out


def extract_activity_timeseries(
    client,
    activity_id,
    activity_name: Optional[str],
    start_time: Optional[datetime],
) -> list[dict[str, Any]]:
    """Fetch FIT file, parse, and return unified timeseries."""
    fit_bytes = fetch_fit_file(client, activity_id)
    if not fit_bytes:
        return []
    return parse_fit_file_to_timeseries(fit_bytes, activity_id, activity_name, start_time)
