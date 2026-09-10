"""Add Drive source metadata and per-object archive checkpoints.

Revision ID: 0012_add_drive_archive_checkpoints
Revises: 0011_add_user_roles
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_add_drive_archive_checkpoints"
down_revision = "0011_add_user_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "archive_import_jobs",
        sa.Column("source_type", sa.String(), nullable=False, server_default="upload"),
    )
    op.add_column("archive_import_jobs", sa.Column("source_locator", sa.String(), nullable=True))
    op.add_column("archive_import_jobs", sa.Column("source_metadata", sa.JSON(), nullable=True))
    op.create_index(
        "ix_archive_import_jobs_source_type", "archive_import_jobs", ["source_type"]
    )
    op.create_table(
        "archive_import_objects",
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
            sa.ForeignKey("archive_import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_object_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=False),
        sa.Column("object_name", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "source_type",
            "source_object_id",
            "source_version",
            name="uq_archive_object_athlete_source_version",
        ),
    )
    for column in ("user_id", "job_id", "provider", "source_type", "status"):
        op.create_index(
            f"ix_archive_import_objects_{column}", "archive_import_objects", [column]
        )


def downgrade() -> None:
    op.drop_table("archive_import_objects")
    op.drop_index("ix_archive_import_jobs_source_type", table_name="archive_import_jobs")
    op.drop_column("archive_import_jobs", "source_metadata")
    op.drop_column("archive_import_jobs", "source_locator")
    op.drop_column("archive_import_jobs", "source_type")
