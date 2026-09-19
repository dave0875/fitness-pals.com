"""Chat endpoint grounded in canonical Postgres fitness context."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import Conversation
from app.types import CurrentUserLike
from app.routes.metrics import summary
from app.llm.client import run_coach_prompt
from app.services.today_plan import build_today_plan


class ChatRequest(BaseModel):
    """Incoming chat payload."""

    message: str


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(
    body: ChatRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Call the LLM after fetching the latest metrics snapshot."""
    metrics = summary(user=user, db=db)
    metrics["today_plan"] = build_today_plan(db, user.id)
    reply = run_coach_prompt(body.message, metrics)
    conv = Conversation(
        user_id=user.id,
        question=body.message,
        answer=reply,
        metadata_json={"metrics": metrics},
    )
    db.add(conv)
    db.commit()
    return {"response": reply}
