"""Authenticated Goal Graph API."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.athlete_goal_graph import build_goal_graph, save_goal_event, save_goal_objective
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/goal-graph", tags=["goal-graph"])


class GoalEventRequest(BaseModel):
    """One athlete-explicit event node."""

    role: str = "supporting"
    event_type: str = "race"
    label: str | None = Field(default=None, max_length=160)
    event_date: date | None = None
    distance: str | None = Field(default=None, max_length=80)
    target_performance: str | None = Field(default=None, max_length=120)
    target_time_seconds: int | None = Field(default=None, gt=0, le=172800)
    priority: int = Field(default=50, ge=1, le=100)
    lifecycle_state: str = "planned"


class GoalObjectiveRequest(BaseModel):
    """One athlete-explicit intermediate objective."""

    event_id: UUID | None = None
    label: str = Field(min_length=1, max_length=200)
    target_date: date | None = None
    priority: int = Field(default=50, ge=1, le=100)
    lifecycle_state: str = "planned"
    details: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def get_goal_graph(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the bounded canonical Goal Graph."""
    return build_goal_graph(db, user.id)


@router.post("/events")
def post_goal_event(
    body: GoalEventRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add one explicit event."""
    return save_goal_event(
        db, user.id, event_id=None, role=body.role, event_type=body.event_type,
        label=body.label, event_date=body.event_date, distance=body.distance,
        target_performance=body.target_performance,
        target_time_seconds=body.target_time_seconds, priority=body.priority,
        lifecycle_state=body.lifecycle_state,
    )


@router.put("/events/{event_id}")
def put_goal_event(
    event_id: UUID,
    body: GoalEventRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace one owned event while retaining its stable identity."""
    return save_goal_event(
        db, user.id, event_id=event_id, role=body.role, event_type=body.event_type,
        label=body.label, event_date=body.event_date, distance=body.distance,
        target_performance=body.target_performance,
        target_time_seconds=body.target_time_seconds, priority=body.priority,
        lifecycle_state=body.lifecycle_state,
    )


@router.post("/objectives")
def post_goal_objective(
    body: GoalObjectiveRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add one explicit intermediate objective."""
    return save_goal_objective(
        db, user.id, objective_id=None, event_id=body.event_id, label=body.label,
        target_date=body.target_date, priority=body.priority,
        lifecycle_state=body.lifecycle_state, details=body.details,
    )


@router.put("/objectives/{objective_id}")
def put_goal_objective(
    objective_id: UUID,
    body: GoalObjectiveRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace one owned intermediate objective."""
    return save_goal_objective(
        db, user.id, objective_id=objective_id, event_id=body.event_id, label=body.label,
        target_date=body.target_date, priority=body.priority,
        lifecycle_state=body.lifecycle_state, details=body.details,
    )
