"""Sleep session model for persisting daily sleep metadata."""

from __future__ import annotations

from sqlalchemy import Date, ForeignKey, JSON, String, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class SleepSession(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Represents a daily sleep session and its summary attributes."""

    __tablename__ = "sleep_sessions"

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    daily_sleep_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    calendar_date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    ingest_run_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_runs.id", ondelete="SET NULL"), nullable=True
    )
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
