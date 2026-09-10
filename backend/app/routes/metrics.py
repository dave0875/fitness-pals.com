"""Postgres-backed athlete insight endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.activity_summary import build_canonical_summary
from app.types import CurrentUserLike


class RaceReadinessRequest(BaseModel):
    """Payload describing an upcoming race for readiness scoring."""

    race_type: str
    race_date: datetime


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post("/summary")
def summary(
    user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Aggregate readiness metrics from canonical athlete activity rows."""
    return build_canonical_summary(db, user.id)


@router.post("/race_readiness")
def race_readiness(
    body: RaceReadinessRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estimate readiness from the athlete's canonical 30-day mileage."""
    summary_data = build_canonical_summary(db, user.id)
    distance_m = float(summary_data["mileage"]["30d"])
    miles_30 = distance_m / 1609.34
    readiness = min(100, max(0, miles_30 / 400 * 100))
    commentary = (
        f"Based on {miles_30:.1f} miles in last 30d, your readiness for a "
        f"{body.race_type} looks {readiness:.0f}/100."
    )
    return {"readiness": readiness, "commentary": commentary}
