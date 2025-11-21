"""Polling helper to discover new conversations in the background."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.models import Conversation

logger = logging.getLogger(__name__)


class ConversationWatchdog:
    """Fetches unseen conversations since the last poll."""

    def __init__(self, db: Session, last_seen: datetime | None = None):
        self.db = db
        self.last_seen = last_seen

    def fetch_new(self, limit: int = 50) -> List[Conversation]:
        """Return all new conversations created after the stored timestamp."""
        query = self.db.query(Conversation).order_by(Conversation.created_at.desc())
        if self.last_seen:
            query = query.filter(Conversation.created_at > self.last_seen)
        conversations = query.limit(limit).all()
        if conversations:
            self.last_seen = max(c.created_at for c in conversations)
        logger.debug(
            "Watchdog fetched %s conversations after %s",
            len(conversations),
            self.last_seen,
        )
        return conversations

    def mark_seen(self, timestamp: datetime | None) -> None:
        """Allow callers to override the last seen marker manually."""
        self.last_seen = timestamp
