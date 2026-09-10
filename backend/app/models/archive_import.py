"""Athlete-owned archive import jobs and object checkpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class ArchiveImportJob(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):
    """One asynchronous import from an upload or a configured Drive folder."""

    __tablename__ = "archive_import_jobs"

    provider: Mapped[str] = mapped_column(String, nullable=False, default="garmin_archive", index=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="upload", index=True)
    source_locator: Mapped[str | None] = mapped_column(String, nullable=True)
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "source_metadata", JSON, nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="upload_pending", index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="application/zip")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    upload_token: Mapped[str | None] = mapped_column(String, nullable=True)
    upload_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column("result", JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column("error", JSON, nullable=True)


class ArchiveImportObject(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):
    """Durable per-object checkpoint and provenance record."""

    __tablename__ = "archive_import_objects"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "source_type",
            "source_object_id",
            "source_version",
            name="uq_archive_object_athlete_source_version",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("archive_import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_object_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[str] = mapped_column(String, nullable=False)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column("result", JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column("error", JSON, nullable=True)
