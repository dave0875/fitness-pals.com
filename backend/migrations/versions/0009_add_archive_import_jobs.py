"""Add archive_import_jobs table.

Revision ID: 0009_add_archive_import_jobs
Revises: 0008_add_published_dossiers
Create Date: 2026-04-14 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_add_archive_import_jobs"
down_revision = "0008_add_published_dossiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create staged archive import job storage."""
    op.create_table(
        "archive_import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False, server_default="garmin_export"),
        sa.Column("status", sa.String(), nullable=False, server_default="upload_pending"),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False, server_default="application/zip"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("upload_token", sa.String(), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upload_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_archive_import_jobs_user_id", "archive_import_jobs", ["user_id"])
    op.create_index("ix_archive_import_jobs_provider", "archive_import_jobs", ["provider"])
    op.create_index("ix_archive_import_jobs_status", "archive_import_jobs", ["status"])
    op.create_index("ix_archive_import_jobs_storage_key", "archive_import_jobs", ["storage_key"], unique=True)


def downgrade() -> None:
    """Drop staged archive import jobs."""
    op.drop_index("ix_archive_import_jobs_storage_key", table_name="archive_import_jobs")
    op.drop_index("ix_archive_import_jobs_status", table_name="archive_import_jobs")
    op.drop_index("ix_archive_import_jobs_provider", table_name="archive_import_jobs")
    op.drop_index("ix_archive_import_jobs_user_id", table_name="archive_import_jobs")
    op.drop_table("archive_import_jobs")
