"""Add private coaching dossier lifecycle tables.

Revision ID: 0008_add_dossiers
Revises: 0007_add_sync_jobs
Create Date: 2026-08-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_add_dossiers"
down_revision = "0007_add_sync_jobs"
branch_labels = None
depends_on = None

json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    """Create owner-scoped dossier jobs and immutable artifacts."""
    op.create_table(
        "dossier_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("request", json_type, nullable=False),
        sa.Column("error", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "snapshot_hash", name="uq_dossier_job_user_snapshot"
        ),
    )
    op.create_index("ix_dossier_jobs_user_id", "dossier_jobs", ["user_id"])
    op.create_index("ix_dossier_jobs_status", "dossier_jobs", ["status"])
    op.create_index("ix_dossier_jobs_snapshot_hash", "dossier_jobs", ["snapshot_hash"])

    op.create_table(
        "dossier_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dossier_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("content", json_type, nullable=False),
        sa.Column("data_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "version", name="uq_dossier_artifact_user_version"
        ),
    )
    op.create_index("ix_dossier_artifacts_user_id", "dossier_artifacts", ["user_id"])
    op.create_index("ix_dossier_artifacts_job_id", "dossier_artifacts", ["job_id"])
    op.create_index(
        "ix_dossier_artifacts_snapshot_hash",
        "dossier_artifacts",
        ["snapshot_hash"],
    )


def downgrade() -> None:
    """Drop dossier lifecycle tables."""
    op.drop_index(
        "ix_dossier_artifacts_snapshot_hash", table_name="dossier_artifacts"
    )
    op.drop_index("ix_dossier_artifacts_job_id", table_name="dossier_artifacts")
    op.drop_index("ix_dossier_artifacts_user_id", table_name="dossier_artifacts")
    op.drop_table("dossier_artifacts")
    op.drop_index("ix_dossier_jobs_snapshot_hash", table_name="dossier_jobs")
    op.drop_index("ix_dossier_jobs_status", table_name="dossier_jobs")
    op.drop_index("ix_dossier_jobs_user_id", table_name="dossier_jobs")
    op.drop_table("dossier_jobs")
