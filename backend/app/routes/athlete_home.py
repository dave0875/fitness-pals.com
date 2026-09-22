"""Authenticated athlete-home endpoint."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AthleteGoal
from app.routes.onboarding import GOAL_COOKIE
from app.services.athlete_home import build_athlete_home
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/athlete-home", tags=["athlete-home"])


@router.get("")
def athlete_home(
    request: Request,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current athlete's journey, readiness, and next action."""
    goal_record = (
        db.query(AthleteGoal)
        .filter(AthleteGoal.user_id == user.id)
        .order_by(AthleteGoal.updated_at.desc())
        .first()
    )
    goal = (
        goal_record.goal_type
        if goal_record is not None
        else request.cookies.get(GOAL_COOKIE)
    )
    return build_athlete_home(db, user.id, goal=goal)
