from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, List

from sqlalchemy.orm import Session

from app.models import Conversation

logger = logging.getLogger(__name__)


class ConversationWatchdog:
    """
    Watches for new conversations (by created_at) and hands back unseen records.
    Intended to be invoked by a scheduler/worker; does not register routes.
    """

    def __init__(self, db: Session, last_seen: datetime | None = None):
        self.db = db
        self.last_seen = last_seen

    def fetch_new(self, limit: int = 50) -> List[Conversation]:
        query = self.db.query(Conversation).order_by(Conversation.created_at.desc())
        if self.last_seen:
            query = query.filter(Conversation.created_at > self.last_seen)
        conversations = query.limit(limit).all()
        if conversations:
            self.last_seen = max(c.created_at for c in conversations)
        logger.debug("Watchdog fetched %s conversations after %s", len(conversations), self.last_seen)
        return conversations
