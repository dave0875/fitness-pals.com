"""Authenticated API for the persisted Today's run coaching loop."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.today_plan import (
    apply_plan_action,
    build_today_plan,
    create_next_plan,
    save_goal,
)
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/today-plan", tags=["today-plan"])


class GoalRequest(BaseModel):
    """An athlete's explicit goal, phase, and optional event date."""

    goal_type: str
    phase: str
    target_date: date | None = None


class PlanActionRequest(BaseModel):
    """One lifecycle action with action-specific values."""

    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def get_today_plan(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return or lazily create the current athlete-owned decision."""
    return build_today_plan(db, user.id)


@router.put("/goal")
def put_goal(
    body: GoalRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist an explicit goal and begin a fresh recommendation."""
    return save_goal(
        db,
        user.id,
        goal_type=body.goal_type,
        phase=body.phase,
        target_date=body.target_date,
    )


@router.patch("/{plan_id}")
def patch_plan(
    plan_id: UUID,
    body: PlanActionRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept, adjust, skip, or complete an owned plan."""
    return apply_plan_action(
        db,
        user.id,
        plan_id,
        action=body.action,
        payload=body.payload,
    )


@router.post("/next")
def post_next_plan(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move a terminal plan back to the next decision."""
    return create_next_plan(db, user.id)
