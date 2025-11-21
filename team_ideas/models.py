"""Simple SQLAlchemy model for storing team ideas."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class TeamIdea(Base):  # pylint: disable=too-few-public-methods
    """Ideas suggested by team members."""

    __tablename__ = "team_ideas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    idea_text = Column(String, nullable=False)
    status = Column(String, nullable=False, default="new")
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
