"""Activity-related ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class Activity(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """
    Canonical activity record after de-duplication. One per workout per user.
    """

    __tablename__ = "activities"

    ingest_run_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    sport: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")  # new | merged | conflict
    fingerprint_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    metadata_json: Mapped[Dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)


class ActivityTrainingEvidence(PrimaryUUIDMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Provider-neutral, one-to-one normalized training evidence for an Activity."""

    __tablename__ = "activity_training_evidence"

    activity_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    ingest_run_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    modality: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_sport: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_sub_sport: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_name: Mapped[str | None] = mapped_column(String, nullable=True)
    timer_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    aerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    structure_json: Mapped[Dict[str, Any] | None] = mapped_column("structure", JSON, nullable=True)
    observed_fields: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    derived_fields: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    field_provenance_json: Mapped[Dict[str, Any] | None] = mapped_column(
        "field_provenance", JSON, nullable=True
    )
    source_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    source_object_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_object_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_object_version: Mapped[str | None] = mapped_column(String, nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class ActivitySource(PrimaryUUIDMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """
    Link back to provider-specific representations for auditability and traceability.
    """

    __tablename__ = "activity_sources"

    activity_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_activity_id: Mapped[str] = mapped_column(String, nullable=False)
    raw_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    decision: Mapped[str] = mapped_column(String, nullable=False, default="new")  # new | merged | duplicate | conflict
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    chosen_fields: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # what fields were taken
    raw_payload: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # optional trimmed payload
    # timestamps provided by mixin


class IngestRun(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a batch ingestion pass for observability.
    """

    __tablename__ = "ingest_runs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


class IngestDecision(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """
    Fine-grained per-activity ingest decisions for transparency/audit.
    """

    __tablename__ = "ingest_decisions"

    ingest_run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_activity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(
        String, nullable=False
    )  # new | merged | duplicate | conflict | skipped_primary
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    fingerprint: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tolerances: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chosen_fields: Mapped[Dict[str, Any] | None] = mapped_column(JSON, nullable=True)
