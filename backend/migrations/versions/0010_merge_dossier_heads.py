"""Merge private-dossier and archive-import migration branches.

Revision ID: 0010_merge_dossier_heads
Revises: 0008_add_dossiers, 0009_add_archive_import_jobs
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations


revision = "0010_merge_dossier_heads"
down_revision = ("0008_add_dossiers", "0009_add_archive_import_jobs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two additive migration branches."""


def downgrade() -> None:
    """Split the migration graph back into its two additive heads."""
