"""Deduplication helpers for ingest runs and transparency logging."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IngestDecision, IngestRun

logger = logging.getLogger("dedupe")


@dataclass
class DedupConfig:
    """Runtime configuration for deduping heuristics."""

    start_time_tolerance_seconds: int = 90
    duration_tolerance_ratio: float = 0.1  # 10%
    distance_tolerance_ratio: float = 0.03  # 3%
    default_sport: str = "run"
    primary_provider: Optional[str] = None  # optional per-user override upstream


@dataclass
class DecisionDetails:  # pylint: disable=too-many-instance-attributes
    """Captured ingest decision metadata."""

    user_id: UUID
    provider: str
    provider_activity_id: Optional[str]
    decision: str
    reason: Optional[str]
    fingerprint: dict
    tolerances: dict
    chosen_fields: Optional[dict] = None


def load_config() -> DedupConfig:
    """Load dedupe configuration from settings with sane defaults."""
    settings = get_settings()
    return DedupConfig(
        start_time_tolerance_seconds=getattr(settings, "dedupe_start_time_tolerance_seconds", 90),
        duration_tolerance_ratio=getattr(settings, "dedupe_duration_tolerance_ratio", 0.1),
        distance_tolerance_ratio=getattr(settings, "dedupe_distance_tolerance_ratio", 0.03),
    )


def fingerprint_activity(
    start_time_iso: str,
    duration_s: Optional[float],
    distance_m: Optional[float],
    sport: str,
) -> str:
    """Return a deterministic hash for identifying duplicate activities."""
    payload = {
        "start": start_time_iso,
        "duration_s": None if duration_s is None else round(duration_s),
        "distance_m": None if distance_m is None else round(distance_m, 1),
        "sport": sport.lower() if sport else None,
    }
    encoded = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def record_ingest_run(db: Session, provider: str) -> IngestRun:
    """Persist the start of an ingest run."""
    run = IngestRun(provider=provider, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_ingest_run(
    db: Session,
    run: IngestRun,
    status: str,
    summary: Optional[dict] = None,
) -> IngestRun:
    """Mark the ingest run as finished and store summary data."""
    run.status = status
    run.finished_at = run.finished_at or datetime.utcnow()
    run.summary = summary
    db.commit()
    db.refresh(run)
    return run


def log_decision(db: Session, run: IngestRun, details: DecisionDetails) -> IngestDecision:
    """Persist an ingest decision and emit structured logs."""
    rec = IngestDecision(
        ingest_run_id=run.id,
        user_id=details.user_id,
        provider=details.provider,
        provider_activity_id=details.provider_activity_id,
        decision=details.decision,
        reason=details.reason,
        fingerprint=details.fingerprint,
        tolerances=details.tolerances,
        chosen_fields=details.chosen_fields,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info(
        "ingest decision",
        extra={
            "provider": details.provider,
            "provider_activity_id": details.provider_activity_id,
            "decision": details.decision,
            "reason": details.reason,
            "fingerprint": details.fingerprint,
        },
    )
    return rec
