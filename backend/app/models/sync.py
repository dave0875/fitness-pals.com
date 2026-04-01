"""Sync job and checkpoint models for provider orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class SyncJob(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Represents a provider sync request owned by the worker layer."""

    __tablename__ = "sync_jobs"

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    test_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column("payload", JSON, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column("result", JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column("error", JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingest_run_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class SyncCheckpoint(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Tracks the most recent successful sync boundary per provider and user."""

    __tablename__ = "sync_checkpoints"

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    cursor_json: Mapped[dict[str, Any] | None] = mapped_column("cursor", JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column("error", JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_job_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sync_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_ingest_run_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
