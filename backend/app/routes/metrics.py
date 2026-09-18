"""Product insight endpoints backed by canonical Postgres records."""

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
    """Aggregate product metrics exclusively from the canonical read model."""
    return build_canonical_summary(db, user.id)


@router.post("/race_readiness")
def race_readiness(
    body: RaceReadinessRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estimate readiness from the same canonical summary used by coaching."""
    metrics = build_canonical_summary(db, user.id)
    response = {
        key: metrics[key]
        for key in ("source", "state", "generated_at", "data_through", "stale_after")
    }
    if metrics["state"] == "error":
        return {
            **response,
            "readiness": None,
            "training_volume_score": None,
            "commentary": (
                "Race readiness is unavailable because canonical fitness data "
                "could not be read."
            ),
            "error": metrics["error"],
        }
    if metrics["state"] == "unknown":
        return {
            **response,
            "readiness": None,
            "training_volume_score": None,
            "commentary": (
                "Race readiness is unknown until canonical activity history is "
                "available."
            ),
            "error": None,
        }

    distance_value = metrics["mileage"]["30d"]
    if distance_value is None:
        return {
            **response,
            "readiness": None,
            "training_volume_score": None,
            "commentary": "Running distance is unknown; race readiness cannot be estimated.",
            "error": None,
        }
    distance_m = float(distance_value)
    miles_30 = distance_m / 1609.34
    volume_score = min(100, max(0, miles_30 / 400 * 100))
    commentary = (
        f"Based on {miles_30:.1f} running miles in the last 30 days, training volume "
        f"for a {body.race_type} is {volume_score:.0f}/100 on this volume-only scale. "
        "Race readiness is unknown without current recovery and intensity signals."
    )
    if metrics["metric_states"]["mileage"] == "stale":
        commentary += " The underlying data is stale; refresh before changing training."
    return {**response, "readiness": None, "training_volume_score": volume_score, "commentary": commentary, "error": None}
