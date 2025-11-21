"""Activity-related ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Activity(Base):  # pylint: disable=too-few-public-methods
    """
    Canonical activity record after de-duplication. One per workout per user.
    """

    __tablename__ = "activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_seconds = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)
    sport = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="new")  # new | merged | conflict
    fingerprint_hash = Column(String, nullable=False, index=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ActivitySource(Base):  # pylint: disable=too-few-public-methods
    """
    Link back to provider-specific representations for auditability and traceability.
    """

    __tablename__ = "activity_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False, index=True)
    provider_activity_id = Column(String, nullable=False)
    raw_hash = Column(String, nullable=True)
    decision = Column(
        String, nullable=False, default="new"
    )  # new | merged | duplicate | conflict
    reason = Column(String, nullable=True)
    chosen_fields = Column(
        JSON, nullable=True
    )  # what fields were taken from this source
    raw_payload = Column(
        JSON, nullable=True
    )  # optional trimmed payload for transparency
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class IngestRun(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a batch ingestion pass for observability.
    """

    __tablename__ = "ingest_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, nullable=False, index=True)
    status = Column(
        String, nullable=False, default="running"
    )  # running | completed | failed
    started_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(JSON, nullable=True)


class IngestDecision(Base):  # pylint: disable=too-few-public-methods
    """
    Fine-grained per-activity ingest decisions for transparency/audit.
    """

    __tablename__ = "ingest_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingest_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False, index=True)
    provider_activity_id = Column(String, nullable=True)
    activity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision = Column(
        String, nullable=False
    )  # new | merged | duplicate | conflict | skipped_primary
    reason = Column(String, nullable=True)
    fingerprint = Column(JSON, nullable=True)
    tolerances = Column(JSON, nullable=True)
    chosen_fields = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
