"""Sleep helpers: persist summaries and write timeseries."""
# mypy: ignore-errors

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, cast

from app.types import CurrentUserLike, InfluxClientLike

from sqlalchemy.orm import Session

logger = logging.getLogger("garmin.sleep")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
logger.propagate = True


def split_sleep_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, list]]:
    """Split sleep payload into summary DTO and timeseries arrays."""
    dto = payload.get("dailySleepDTO") or {}
    series = {k: v for k, v in payload.items() if k != "dailySleepDTO" and isinstance(v, list)}
    return dto, series


def persist_sleep_session(
    db: Session,
    user_id,
    provider: str,
    dto: Dict[str, Any],
    ingest_run_id=None,
    test_run: bool = False,
):
    """Upsert a sleep session row keyed by user+provider+daily_sleep_id."""
    from app.models.sleep import SleepSession  # local import to avoid circular

    calendar_date = dto.get("calendarDate")
    base_sleep_id = dto.get("id")
    if base_sleep_id is None and calendar_date:
        try:
            base_sleep_id = int(calendar_date.replace("-", ""))
        except Exception:
            base_sleep_id = None
    if base_sleep_id is None:
        return None
    sleep_id = base_sleep_id
    if test_run and ingest_run_id:
        mod = abs(hash(str(ingest_run_id))) % 900 + 1
        sleep_id = int(f"{base_sleep_id}{mod:03d}")
    existing = (
        db.query(SleepSession)
        .filter(
            SleepSession.user_id == user_id,
            SleepSession.provider == provider,
            SleepSession.daily_sleep_id == sleep_id,
        )
        .first()
    )
    if existing:
        existing.calendar_date = cast(Any, calendar_date)
        existing.summary_json = cast(Any, dto)
        existing.ingest_run_id = ingest_run_id or existing.ingest_run_id
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    rec = SleepSession(
        user_id=user_id,
        provider=provider,
        daily_sleep_id=sleep_id,
        calendar_date=calendar_date,
        summary_json=dto,
        ingest_run_id=ingest_run_id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def write_sleep_series(
    client: InfluxClientLike,
    user: CurrentUserLike,
    sleep_id,
    series: Dict[str, list],
    run,
    ingest_run_tag: Optional[str] = None,
) -> Dict[str, int]:
    """Write sleep timeseries arrays to Influx with consistent tagging."""
    written_counts: Dict[str, int] = {}
    ingest_run_tag = ingest_run_tag or str(getattr(run, "id", ""))
    logger.info(
        "sleep timeseries write start",
        extra={
            "user_id": str(getattr(user, "id", "")),
            "sleep_id": sleep_id,
            "ingest_run_id": ingest_run_tag,
            "series_keys": list(series.keys()),
        },
    )
    measurement_map = {
        "sleepMovement": "SleepMovement",
        "sleepLevels": "SleepLevels",
        "sleepBodyBattery": "SleepBodyBattery",
        "hrvData": "SleepHRV",
        "breathingDisruptionData": "SleepBreathingDisruption",
        "wellnessEpochSPO2DataDTOList": "SleepSpO2",
        "wellnessEpochRespirationDataDTOList": "SleepRespiration",
        "sleepRestlessMoments": "SleepRestlessness",
        "sleepHeartRate": "SleepHeartRate",
        "sleepStress": "SleepStress",
    }
    for key, items in series.items():
        measurement = measurement_map.get(key)
        if not measurement:
            continue
        points = []
        for item in items:
            start = item.get("startGMT") or item.get("epochTimestamp")
            if start is None:
                continue
            try:
                ts = int(str(start))
            except Exception:
                continue
            fields = {}
            if "value" in item:
                fields["value"] = item.get("value")
            if "activityLevel" in item:
                fields["activity_level"] = item.get("activityLevel")
            if "spo2Reading" in item:
                fields["spo2"] = item.get("spo2Reading")
            if "respirationValue" in item:
                fields["respiration"] = item.get("respirationValue")
            if "endGMT" in item:
                fields["end_gmt"] = item.get("endGMT")
            if not fields:
                continue
            points.append(
                {
                    "measurement": measurement,
                    "time": ts,
                    "tags": {
                        "user_id": str(user.id),
                        "sleep_id": str(sleep_id),
                        "ingest_run_id": ingest_run_tag if run else None,
                        "provider": "garmin",
                    },
                    "fields": fields,
                }
            )
        if points:
            write_api = client.write_api()
            write_api.write(bucket=client.default_bucket, org=client.org, record=points)
            written_counts[key] = len(points)
            logger.info(
                "sleep timeseries measurement written",
                extra={
                    "measurement": measurement,
                    "key": key,
                    "count": len(points),
                    "user_id": str(getattr(user, "id", "")),
                    "sleep_id": sleep_id,
                    "ingest_run_id": ingest_run_tag,
                },
            )
    if not written_counts:
        logger.info(
            "sleep timeseries write finished with no points",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "sleep_id": sleep_id,
                "ingest_run_id": ingest_run_tag,
            },
        )
    return written_counts
