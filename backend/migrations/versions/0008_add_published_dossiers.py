"""Add published_dossiers table.

Revision ID: 0008_add_published_dossiers
Revises: 0007_add_sync_jobs
Create Date: 2026-04-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_add_published_dossiers"
down_revision = "0007_add_sync_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create published dossier storage."""
    op.create_table(
        "published_dossiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("athlete_name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column(
            "public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("html_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_published_dossiers_user_id",
        "published_dossiers",
        ["user_id"],
    )
    op.create_index(
        "ix_published_dossiers_slug",
        "published_dossiers",
        ["slug"],
        unique=True,
    )


def downgrade() -> None:
    """Drop published dossier storage."""
    op.drop_index("ix_published_dossiers_slug", table_name="published_dossiers")
    op.drop_index("ix_published_dossiers_user_id", table_name="published_dossiers")
    op.drop_table("published_dossiers")
