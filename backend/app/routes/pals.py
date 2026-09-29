"""Authenticated same-origin Pal adapter routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.routes.chat import ChatRequest, chat as coach_chat
from app.services.pal_adapter import (
    ADAPTER_VERSION,
    PERSONA_BY_ID,
    InvalidPalSessionError,
    InvalidPersonaError,
    PalAdapter,
    PalAdapterError,
)
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/pals/v1", tags=["pals"])


class PalSessionRequest(BaseModel):
    """Start a bounded Pal adapter session from one canonical public persona id."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(min_length=1, max_length=80)


class PalTurnRequest(BaseModel):
    """Submit one text turn through an opaque adapter session."""

    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(min_length=32, max_length=8192)
    message: str = Field(min_length=1, max_length=2000)


def get_pal_adapter() -> PalAdapter:
    """Build the server-side adapter from operator-controlled settings."""
    return PalAdapter(get_settings())


def _fallback_contract(reason: str | None) -> dict[str, object]:
    return {
        "active": True,
        "mode": "coach",
        "href": "/coach",
        "reason": reason or "pal_runtime_unavailable",
    }


@router.get("/personas")
def list_personas(
    _user: CurrentUserLike = Depends(get_current_user),
    adapter: PalAdapter = Depends(get_pal_adapter),
):
    """Discover public Pal identities and truthful runtime availability."""
    return adapter.discovery()


@router.post("/sessions")
def start_pal_session(
    body: PalSessionRequest,
    user: CurrentUserLike = Depends(get_current_user),
    adapter: PalAdapter = Depends(get_pal_adapter),
):
    """Create an opaque user-owned adapter session without asserting myChat identity."""
    try:
        session, token, reason = adapter.start_session(str(user.id), body.persona_id)
    except InvalidPersonaError as exc:
        raise HTTPException(status_code=404, detail="Pal persona not found") from exc

    public = PERSONA_BY_ID[session.persona_id]
    is_pal = session.mode == "pal"
    return {
        "adapter_version": ADAPTER_VERSION,
        "session_token": token,
        "mode": session.mode,
        "requested_persona_id": session.persona_id,
        "active_persona_id": session.persona_id if is_pal else None,
        "speaker": public["display_name"] if is_pal else "Coach",
        "fallback": _fallback_contract(reason) if not is_pal else None,
    }


@router.post("/turns")
def submit_pal_turn(
    body: PalTurnRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: PalAdapter = Depends(get_pal_adapter),
):
    """Run one Pal turn or preserve the question through the durable Coach fallback."""
    try:
        session = adapter.decode_session(body.session_token, str(user.id))
    except InvalidPalSessionError as exc:
        raise HTTPException(status_code=400, detail="Pal session is invalid or expired") from exc

    if session.mode == "pal":
        try:
            turn = adapter.submit_upstream_turn(session, body.message)
            return {
                "adapter_version": ADAPTER_VERSION,
                "session_token": body.session_token,
                "mode": "pal",
                "requested_persona_id": session.persona_id,
                "active_persona_id": session.persona_id,
                "speaker": PERSONA_BY_ID[session.persona_id]["display_name"],
                "answer": turn["answer"],
                "voice": {
                    "voice_key": turn["voice_key"],
                    "available": turn["voice_available"],
                    "autoplay": False,
                },
                "fallback": None,
            }
        except PalAdapterError:
            # The private upstream failed. Preserve the user's question by routing
            # it into the existing durable Coach instead of losing or faking a Pal turn.
            session, _token = adapter.fallback_session(
                session,
                coach_thread_id=session.coach_thread_id,
            )

    thread_id = UUID(session.coach_thread_id) if session.coach_thread_id else None
    coach = coach_chat(
        ChatRequest(message=body.message, thread_id=thread_id),
        user=user,
        db=db,
    )
    coach_thread_id = str(coach["thread"]["id"])
    _updated, token = adapter.fallback_session(
        session,
        coach_thread_id=coach_thread_id,
    )
    return {
        "adapter_version": ADAPTER_VERSION,
        "session_token": token,
        "mode": "coach-fallback",
        "requested_persona_id": session.persona_id,
        "active_persona_id": None,
        "speaker": "Coach",
        "answer": coach["turn"].get("answer"),
        "voice": None,
        "fallback": _fallback_contract("pal_runtime_unavailable"),
        "coach": coach,
    }
