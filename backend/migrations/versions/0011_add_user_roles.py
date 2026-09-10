"""Add explicit application roles to users.

Revision ID: 0011_add_user_roles
Revises: 0010_merge_dossier_heads
Create Date: 2026-09-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_add_user_roles"
down_revision = "0010_merge_dossier_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an athlete-defaulted role for existing and future users."""
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=32),
            server_default="athlete",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove application roles from users."""
    op.drop_column("users", "role")
