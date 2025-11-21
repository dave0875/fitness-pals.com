"""Prototype router for capturing/summarizing internal ideas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from .services import list_ideas, submit_idea, summarize_for_tasks


class IdeaRequest(BaseModel):
    """Incoming payload for a new idea."""

    text: str


router = APIRouter(prefix="/api/team-ideas", tags=["team-ideas"])


@router.post("")
def create_idea(
    body: IdeaRequest, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """Persist a new idea for the current user."""
    return submit_idea(db, user, body.text)


@router.get("")
def get_ideas(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the requesting user's ideas."""
    return list_ideas(db, user)


@router.get("/summary")
def summarize(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Summarize stored ideas via a text prompt."""
    ideas = list_ideas(db, user)
    if not ideas:
        raise HTTPException(status_code=404, detail="No ideas")
    return {"summary_prompt": summarize_for_tasks(ideas)}
