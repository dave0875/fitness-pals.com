"""Store Q/A conversations for audit/history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, UserOwnedMixin


class Conversation(PrimaryUUIDMixin, UserOwnedMixin, Base):  # pylint: disable=too-few-public-methods
    """Agents' historical conversations and answers."""

    __tablename__ = "conversations"

    question: Mapped[str] = mapped_column(String, nullable=False)
    answer: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
