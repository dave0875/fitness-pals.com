from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, ActivitySource, IngestDecision, IngestRun

logger = logging.getLogger("dedupe")


@dataclass
class DedupConfig:
    start_time_tolerance_seconds: int = 90
    duration_tolerance_ratio: float = 0.1  # 10%
    distance_tolerance_ratio: float = 0.03  # 3%
    default_sport: str = "run"
    primary_provider: Optional[str] = None  # optional per-user override upstream


def load_config() -> DedupConfig:
    settings = get_settings()
    return DedupConfig(
        start_time_tolerance_seconds=getattr(settings, "dedupe_start_time_tolerance_seconds", 90),
        duration_tolerance_ratio=getattr(settings, "dedupe_duration_tolerance_ratio", 0.1),
        distance_tolerance_ratio=getattr(settings, "dedupe_distance_tolerance_ratio", 0.03),
    )


def fingerprint_activity(start_time_iso: str, duration_s: Optional[float], distance_m: Optional[float], sport: str) -> str:
    payload = {
        "start": start_time_iso,
        "duration_s": None if duration_s is None else round(duration_s),
        "distance_m": None if distance_m is None else round(distance_m, 1),
        "sport": sport.lower() if sport else None,
    }
    encoded = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def record_ingest_run(db: Session, provider: str) -> IngestRun:
    run = IngestRun(provider=provider, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_ingest_run(db: Session, run: IngestRun, status: str, summary: Optional[dict] = None) -> IngestRun:
    run.status = status
    run.finished_at = run.finished_at or datetime.utcnow()
    run.summary = summary
    db.commit()
    db.refresh(run)
    return run


def log_decision(
    db: Session,
    run: IngestRun,
    *,
    user_id,
    provider: str,
    provider_activity_id: Optional[str],
    decision: str,
    reason: Optional[str],
    fingerprint: dict,
    tolerances: dict,
    chosen_fields: Optional[dict] = None,
) -> IngestDecision:
    rec = IngestDecision(
        ingest_run_id=run.id,
        user_id=user_id,
        provider=provider,
        provider_activity_id=provider_activity_id,
        decision=decision,
        reason=reason,
        fingerprint=fingerprint,
        tolerances=tolerances,
        chosen_fields=chosen_fields,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info(
        "ingest decision",
        extra={
            "provider": provider,
            "provider_activity_id": provider_activity_id,
            "decision": decision,
            "reason": reason,
            "fingerprint": fingerprint,
        },
    )
    return rec
