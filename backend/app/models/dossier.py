"""Private athlete coaching dossier jobs and immutable artifacts."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class DossierJob(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Asynchronous request to generate one bounded athlete dossier snapshot."""

    __tablename__ = "dossier_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_hash", name="uq_dossier_job_user_snapshot"),
    )

    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_json: Mapped[dict] = mapped_column("request", JSON, nullable=False)
    error_json: Mapped[dict | None] = mapped_column("error", JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DossierArtifact(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Immutable generated dossier version owned by exactly one athlete."""

    __tablename__ = "dossier_artifacts"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_dossier_artifact_user_version"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dossier_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_json: Mapped[dict] = mapped_column("content", JSON, nullable=False)
    data_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
