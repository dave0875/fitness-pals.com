"""Athlete State API backed by the canonical recovery read model."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.athlete_state import build_athlete_state
from app.types import CurrentUserLike

router = APIRouter(prefix="/api/athlete-state", tags=["athlete-state"])


@router.get("")
def athlete_state(
    days: int = Query(default=14, ge=1, le=90),
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one athlete's normalized latest recovery state and bounded history."""
    return build_athlete_state(db, user.id, days=days)
