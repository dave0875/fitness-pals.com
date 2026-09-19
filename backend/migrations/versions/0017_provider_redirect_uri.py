"""Store OAuth callback URIs with encrypted provider app registrations.

Revision ID: 0017_provider_redirect_uri
Revises: 0016_today_plan
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_provider_redirect_uri"
down_revision = "0016_today_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the non-secret callback URI to shared OAuth app metadata."""
    op.add_column("provider_apps", sa.Column("redirect_uri", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove OAuth callback metadata without touching encrypted credentials."""
    op.drop_column("provider_apps", "redirect_uri")
