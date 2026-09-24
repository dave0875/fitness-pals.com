"""Persisted athlete goals and next-session coaching decisions."""

from __future__ import annotations

from datetime import date, datetime
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class AthleteGoal(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """One explicit, account-owned coaching goal and phase."""

    __tablename__ = "athlete_goals"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_athlete_goal_user"),
    )

    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intent_json: Mapped[dict | None] = mapped_column("intent", JSON, nullable=True)


class NextSessionPlan(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """A versioned next-session recommendation and its decision lifecycle."""

    __tablename__ = "next_session_plans"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("athlete_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    session_purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    scheduled_for: Mapped[date] = mapped_column(Date, nullable=False)
    recommendation_json: Mapped[dict] = mapped_column("recommendation", JSON, nullable=False)
    rationale_json: Mapped[dict] = mapped_column("rationale", JSON, nullable=False)
    adjustment_json: Mapped[dict | None] = mapped_column("adjustment", JSON, nullable=True)
    feedback_json: Mapped[dict | None] = mapped_column("feedback", JSON, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AthleteGoalEvent(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """One explicit event node in an athlete-owned Goal Graph."""

    __tablename__ = "athlete_goal_events"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("athlete_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    distance_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_performance: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    provenance_json: Mapped[dict | None] = mapped_column("provenance", JSON, nullable=True)


class AthleteGoalObjective(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """One explicit intermediate objective in an athlete-owned Goal Graph."""

    __tablename__ = "athlete_goal_objectives"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("athlete_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("athlete_goal_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    details_json: Mapped[dict | None] = mapped_column("details", JSON, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column("provenance", JSON, nullable=True)
