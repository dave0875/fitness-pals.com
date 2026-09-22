"""Persist richer Product V2 athlete activation intent.

Revision ID: 0018_activation_intent
Revises: 0017_provider_redirect_uri
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_activation_intent"
down_revision = "0017_provider_redirect_uri"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend the existing durable athlete goal without creating onboarding state."""
    op.add_column("athlete_goals", sa.Column("intent", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove only the optional Product V2 intent payload."""
    op.drop_column("athlete_goals", "intent")
