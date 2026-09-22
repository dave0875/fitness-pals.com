"""Athlete-scoped intelligence and deliberate coaching-preference APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.athlete_intelligence import (
    build_athlete_intelligence,
    save_coaching_preferences,
)
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class CoachingPreferencesRequest(BaseModel):
    """Preferences the athlete explicitly asks Coach to remember."""

    preferences: list[str] = Field(default_factory=list, max_length=8)


@router.get("")
def intelligence(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return bounded athlete-to-self intelligence from canonical records."""
    return build_athlete_intelligence(db, user.id)


@router.patch("/preferences")
def update_preferences(
    body: CoachingPreferencesRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save or clear only deliberate coaching preferences."""
    save_coaching_preferences(db, user.id, body.preferences)
    return build_athlete_intelligence(db, user.id)
