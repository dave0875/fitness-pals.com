"""Add sync job and checkpoint tables.

Revision ID: 0007_add_sync_jobs
Revises: 0006_merge_heads
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_add_sync_jobs"
down_revision = "0006_merge_heads"
branch_labels = None
depends_on = None

json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    """Create sync orchestration tables."""
    op.create_table(
        "sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(), nullable=False, server_default="manual"),
        sa.Column("test_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("payload", json_type, nullable=True),
        sa.Column("result", json_type, nullable=True),
        sa.Column("error", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingest_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sync_jobs_user_id", "sync_jobs", ["user_id"])
    op.create_index("ix_sync_jobs_provider", "sync_jobs", ["provider"])
    op.create_index("ix_sync_jobs_status", "sync_jobs", ["status"])
    op.create_index("ix_sync_jobs_ingest_run_id", "sync_jobs", ["ingest_run_id"])

    op.create_table(
        "sync_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="idle"),
        sa.Column("cursor", json_type, nullable=True),
        sa.Column("error", json_type, nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_sync_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sync_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_ingest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingest_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sync_checkpoints_user_id", "sync_checkpoints", ["user_id"])
    op.create_index("ix_sync_checkpoints_provider", "sync_checkpoints", ["provider"])
    op.create_index("ix_sync_checkpoints_last_sync_job_id", "sync_checkpoints", ["last_sync_job_id"])
    op.create_index("ix_sync_checkpoints_last_ingest_run_id", "sync_checkpoints", ["last_ingest_run_id"])
    op.create_index(
        "ix_sync_checkpoints_user_provider",
        "sync_checkpoints",
        ["user_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    """Drop sync orchestration tables."""
    op.drop_index("ix_sync_checkpoints_user_provider", table_name="sync_checkpoints")
    op.drop_index("ix_sync_checkpoints_last_ingest_run_id", table_name="sync_checkpoints")
    op.drop_index("ix_sync_checkpoints_last_sync_job_id", table_name="sync_checkpoints")
    op.drop_index("ix_sync_checkpoints_provider", table_name="sync_checkpoints")
    op.drop_index("ix_sync_checkpoints_user_id", table_name="sync_checkpoints")
    op.drop_table("sync_checkpoints")

    op.drop_index("ix_sync_jobs_ingest_run_id", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_status", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_provider", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_user_id", table_name="sync_jobs")
    op.drop_table("sync_jobs")
