"""Privacy-safe, allowlisted UX telemetry for Product Experience V2."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.deps import get_current_user
from app.types import CurrentUserLike


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ux-events", tags=["ux"])


class UxEvent(BaseModel):
    """Bounded UX signal. No athlete content, identifiers, URLs, or metric values."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["surface_view", "action", "recovery_view"]
    surface: Literal[
        "today",
        "coach",
        "progress",
        "training",
        "settings",
        "welcome",
        "archive",
        "public",
    ]
    action: Literal[
        "ask_coach",
        "retry",
        "refresh",
        "filter",
        "plan_update",
        "connect",
        "import",
        "sign_out",
    ] | None = None
    state: Literal[
        "ready",
        "loading",
        "empty",
        "fresh",
        "stale",
        "partial",
        "failed",
        "disconnected",
        "authorization_expired",
        "unavailable",
    ] | None = None
    viewport: Literal["mobile", "tablet", "desktop"]


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def record_ux_event(
    event: UxEvent,
    user: CurrentUserLike = Depends(get_current_user),
) -> Response:
    """Record only an anonymous, allowlisted product-usage shape."""
    del user
    payload = event.model_dump(exclude_none=True)
    logger.info("ux event", extra={"ux_event": payload})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
