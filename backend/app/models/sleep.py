"""Sleep session model for persisting daily sleep metadata."""

from __future__ import annotations

import uuid
from datetime import datetime, date

from sqlalchemy import Column, Date, DateTime, ForeignKey, JSON, String, BigInteger
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class SleepSession(Base):  # pylint: disable=too-few-public-methods
    """Represents a daily sleep session and its summary attributes."""

    __tablename__ = "sleep_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    daily_sleep_id = Column(BigInteger, nullable=False, index=True)
    calendar_date = Column(Date, nullable=False, index=True)
    ingest_run_id = Column(UUID(as_uuid=True), ForeignKey("ingest_runs.id", ondelete="SET NULL"), nullable=True)
    summary_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
