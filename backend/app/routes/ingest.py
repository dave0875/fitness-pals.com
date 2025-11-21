"""Endpoints that expose ingest run transparency details."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import IngestDecision, IngestRun, User


router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/runs")
def list_runs(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return recent ingest runs."""
    runs = db.query(IngestRun).order_by(IngestRun.started_at.desc()).limit(200).all()
    return [
        {
            "id": str(run.id),
            "provider": run.provider,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "summary": run.summary,
        }
        for run in runs
    ]


@router.get("/runs/{run_id}")
def get_run(
    run_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Return metadata for a specific ingest run."""
    run = db.query(IngestRun).filter(IngestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": str(run.id),
        "provider": run.provider,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": run.summary,
    }


@router.get("/runs/{run_id}/decisions")
def list_decisions(
    run_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Return fine-grained decisions for an ingest batch."""
    decisions = (
        db.query(IngestDecision)
        .filter(IngestDecision.ingest_run_id == run_id)
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
