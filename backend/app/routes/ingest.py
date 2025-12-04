"""Endpoints that expose ingest run transparency details."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import IngestDecision, IngestRun
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/ingest", tags=["ingest"])
logger = logging.getLogger("routes.ingest")


def _parse_run_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid run id format") from exc


def _user_run_ids(db: Session, user_id: UUID) -> set[UUID]:
    """Return run ids that have decisions recorded for the user."""
    decision_rows = (
        db.query(IngestDecision)
        .filter(IngestDecision.user_id == user_id)
        .all()
    )
    return {
        UUID(str(row.ingest_run_id))
        for row in decision_rows
        if getattr(row, "ingest_run_id", None)
    }


def _run_visible_to_user(run: IngestRun, user: CurrentUserLike, decision_run_ids: set[UUID]) -> bool:
    """Check whether a run is associated with the given user."""
    run_user_id = UUID(str(run.user_id)) if getattr(run, "user_id", None) else None
    return (run_user_id == user.id) or (run.id in decision_run_ids)


@router.get("/runs")
def list_runs(user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return recent ingest runs."""
    user_uuid = UUID(str(user.id))
    decision_run_ids = _user_run_ids(db, user_uuid)
    runs = db.query(IngestRun).order_by(IngestRun.started_at.desc()).limit(200).all()
    visible_runs = [run for run in runs if _run_visible_to_user(run, user, decision_run_ids)]
    return [
        _serialize_run(run)
        for run in visible_runs
    ]


@router.get("/runs/{run_id}")
def get_run(
    run_id: str, user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Return metadata for a specific ingest run."""
    run_uuid = _parse_run_id(run_id)
    user_uuid = UUID(str(user.id))
    decision_run_ids = _user_run_ids(db, user_uuid)
    run = db.query(IngestRun).filter(IngestRun.id == run_uuid).first()
    if not run or not _run_visible_to_user(run, user, decision_run_ids):
        logger.info("ingest run not visible", extra={"run_id": run_id, "user_id": str(user.id)})
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)


@router.get("/runs/{run_id}/decisions")
def list_decisions(
    run_id: str, user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Return fine-grained decisions for an ingest batch."""
    run_uuid = _parse_run_id(run_id)
    user_uuid = UUID(str(user.id))
    decision_run_ids = _user_run_ids(db, user_uuid)
    run = db.query(IngestRun).filter(IngestRun.id == run_uuid).first()
    if not run or not _run_visible_to_user(run, user, decision_run_ids):
        raise HTTPException(status_code=404, detail="Run not found")
    decisions = (
        db.query(IngestDecision)
        .filter(
            IngestDecision.ingest_run_id == run_uuid,
            IngestDecision.user_id == user.id,
        )
        .order_by(IngestDecision.created_at)
        .all()
    )
    return [
        {
            "id": str(decision.id),
            "provider": decision.provider,
            "provider_activity_id": decision.provider_activity_id,
            "activity_id": str(decision.activity_id) if decision.activity_id else None,
            "user_id": str(decision.user_id),
            "decision": decision.decision,
            "reason": decision.reason,
            "fingerprint": decision.fingerprint,
            "tolerances": decision.tolerances,
            "chosen_fields": decision.chosen_fields,
            "created_at": decision.created_at,
        }
        for decision in decisions
    ]


def _serialize_run(run: IngestRun) -> dict:
    return {
        "id": str(run.id),
        "provider": run.provider,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": run.summary,
    }
