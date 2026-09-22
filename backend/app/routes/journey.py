"""Authenticated journey and activity-detail endpoints."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.routes.onboarding import GOAL_COOKIE
from app.services.journey import build_activity_detail, build_journey
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/journey", tags=["journey"])


@router.get("")
def journey(
    request: Request,
    window: Literal["30d", "90d", "365d", "all"] = Query("90d"),
    sport: str = Query("all", min_length=1, max_length=40),
    goal: str = Query(
        "all", min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$"
    ),
    activity_page: int = Query(1, ge=1),
    activity_page_size: int = Query(25, ge=1, le=100),
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current athlete's filterable canonical journey."""
    return build_journey(
        db,
        user.id,
        window=window,
        sport=sport,
        goal=request.cookies.get(GOAL_COOKIE),
        goal_filter=goal,
        activity_page=activity_page,
        activity_page_size=activity_page_size,
    )


@router.get("/activities/{activity_id}")
def activity_detail(
    activity_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one current-athlete canonical activity and safe provenance."""
    return build_activity_detail(db, user.id, activity_id)
