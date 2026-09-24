"""Canonical athlete recovery state derived from user-owned Postgres records."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any
from uuid import UUID

from app.models import SleepSession
from app.services.athlete_intent import build_future_intent
from app.services.training_evidence import build_whole_training_summary

FRESHNESS_WINDOW = timedelta(hours=72)
MAX_HISTORY_DAYS = 90


def _utc_day_end(value: date) -> datetime:
    """Represent a date-only recovery observation without inventing provider time."""
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    """Return a finite numeric value while preserving missing/invalid as unknown."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _direct(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _sleep_duration_hours(payload: dict[str, Any]) -> float | None:
    seconds = _number(
        _direct(
            payload,
            "sleepTimeSeconds",
            "totalSleepSeconds",
            "durationSeconds",
            "sleep_time_seconds",
        )
    )
    return round(seconds / 3600.0, 2) if seconds is not None else None


def _sleep_score(payload: dict[str, Any]) -> float | None:
    scores = payload.get("sleepScores")
    if isinstance(scores, dict):
        overall = scores.get("overall")
        if isinstance(overall, dict):
            overall = _direct(overall, "value", "score")
        value = _number(overall)
        if value is not None:
            return value
    return _number(_direct(payload, "sleepScore", "overallSleepScore", "sleep_score"))


def _overnight_hrv(payload: dict[str, Any]) -> float | None:
    value = _number(_direct(payload, "avgOvernightHrv", "overnightHrv"))
    if value is not None:
        return value
    hrv = payload.get("hrv")
    if isinstance(hrv, dict):
        return _number(_direct(hrv, "lastNightAvg", "avgOvernightHrv", "overnightHrv"))
    value = _number(hrv)
    if value is not None:
        return value
    summary = payload.get("hrvSummary")
    if isinstance(summary, dict):
        return _number(_direct(summary, "lastNightAvg", "avgOvernightHrv", "overnightHrv"))
    return None


def _resting_heart_rate(payload: dict[str, Any]) -> float | None:
    return _number(
        _direct(
            payload,
            "restingHeartRate",
            "restingHeartRateValue",
            "resting_heart_rate",
        )
    )


def _provenance(session: SleepSession) -> dict[str, Any]:
    return {
        "canonical_model": "sleep_session",
        "record_id": str(session.id) if getattr(session, "id", None) is not None else None,
        "provider": getattr(session, "provider", None),
        "provider_record_id": str(getattr(session, "daily_sleep_id", "")) or None,
        "ingest_run_id": (
            str(session.ingest_run_id) if getattr(session, "ingest_run_id", None) else None
        ),
    }


def _signal(
    value: float | None,
    unit: str,
    observation_date: date,
    now: datetime,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    stale_after = _utc_day_end(observation_date) + FRESHNESS_WINDOW
    status = "unavailable" if value is None else ("stale" if now > stale_after else "known")
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "observation_date": observation_date.isoformat(),
        "stale_after": stale_after.isoformat(),
        "provenance": provenance,
    }


def _rows_for_athlete(db, user_id: UUID) -> list[SleepSession]:
    """Apply a database user predicate and retain a defensive ownership check."""
    query = db.query(SleepSession)
    if hasattr(query, "filter"):
        query = query.filter(SleepSession.user_id == user_id)
    rows = query.all()
    owned = [row for row in rows if getattr(row, "user_id", None) == user_id]
    return sorted(
        owned,
        key=lambda row: (
            getattr(row, "calendar_date", date.min),
            str(getattr(row, "provider", "")),
            str(getattr(row, "id", "")),
        ),
        reverse=True,
    )


def _day_state(rows: list[SleepSession], observation_date: date, now: datetime) -> dict[str, Any]:
    """Merge duplicate canonical source rows per day without merging athletes."""
    extractors = {
        "sleep_duration": (_sleep_duration_hours, "hours"),
        "sleep_score": (_sleep_score, "score"),
        "overnight_hrv": (_overnight_hrv, "ms"),
        "resting_heart_rate": (_resting_heart_rate, "bpm"),
    }
    signals: dict[str, Any] = {}
    for name, (extractor, unit) in extractors.items():
        selected_value = None
        selected_provenance = _provenance(rows[0])
        for row in rows:
            payload = row.summary_json if isinstance(row.summary_json, dict) else {}
            candidate = extractor(payload)
            if candidate is not None:
                selected_value = candidate
                selected_provenance = _provenance(row)
                break
        signals[name] = _signal(
            selected_value,
            unit,
            observation_date,
            now,
            selected_provenance,
        )

    known = [signal for signal in signals.values() if signal["value"] is not None]
    if not known:
        state = "unknown"
    elif all(signal["status"] == "stale" for signal in known):
        state = "stale"
    else:
        state = "fresh"

    return {
        "date": observation_date.isoformat(),
        "state": state,
        "data_through": observation_date.isoformat(),
        "signals": signals,
    }


def build_athlete_state(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """Return latest and bounded historical recovery state for one athlete."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)
    history_days = max(1, min(int(days), MAX_HISTORY_DAYS))
    training_state = build_whole_training_summary(db, user_id, now=current_time, days=30)
    future_intent = build_future_intent(db, user_id, now=current_time)

    try:
        rows = _rows_for_athlete(db, user_id)
    except Exception:  # pylint: disable=broad-except
        return {
            "source": "canonical_postgres",
            "state": "error",
            "generated_at": current_time.isoformat(),
            "data_through": None,
            "latest": None,
            "history": [],
            "training": training_state,
            "future_intent": future_intent,
            "derived": {
                "hrv_7d_average": {
                    "value": None,
                    "unit": "ms",
                    "status": "unavailable",
                    "window_days": 7,
                    "sample_count": 0,
                }
            },
            "error": {
                "code": "canonical_recovery_read_failed",
                "message": "Canonical recovery data is temporarily unavailable.",
            },
        }

    grouped_all: dict[date, list[SleepSession]] = {}
    for row in rows:
        observation_date = getattr(row, "calendar_date", None)
        if isinstance(observation_date, date) and observation_date <= current_time.date():
            grouped_all.setdefault(observation_date, []).append(row)

    latest_day = max(grouped_all, default=None)
    latest = (
        _day_state(grouped_all[latest_day], latest_day, current_time)
        if latest_day is not None
        else None
    )

    cutoff = current_time.date() - timedelta(days=history_days - 1)
    history = [
        _day_state(grouped_all[day], day, current_time)
        for day in sorted(grouped_all, reverse=True)
        if day >= cutoff
    ]

    hrv_cutoff = current_time.date() - timedelta(days=6)
    hrv_states = [
        _day_state(grouped_all[day], day, current_time)
        for day in sorted(grouped_all, reverse=True)
        if day >= hrv_cutoff
    ]
    hrv_values = [
        item["signals"]["overnight_hrv"]["value"]
        for item in hrv_states
        if item["signals"]["overnight_hrv"]["value"] is not None
    ]
    hrv_average = round(sum(hrv_values) / len(hrv_values), 2) if hrv_values else None
    latest_hrv = latest["signals"]["overnight_hrv"] if latest else None
    hrv_status = (
        "unavailable"
        if hrv_average is None
        else ("stale" if latest_hrv and latest_hrv["status"] == "stale" else "known")
    )

    return {
        "source": "canonical_postgres",
        "state": latest["state"] if latest else "unknown",
        "generated_at": current_time.isoformat(),
        "data_through": latest["data_through"] if latest else None,
        "latest": latest,
        "history": history,
        "training": training_state,
        "future_intent": future_intent,
        "derived": {
            "hrv_7d_average": {
                "value": hrv_average,
                "unit": "ms",
                "status": hrv_status,
                "window_days": 7,
                "sample_count": len(hrv_values),
            }
        },
        "error": None,
    }
