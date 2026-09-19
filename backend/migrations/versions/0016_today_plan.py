"""Persist athlete goals and next-session coaching decisions.

Revision ID: 0016_today_plan
Revises: 0015_remove_pulsai
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_today_plan"
down_revision = "0015_remove_pulsai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create private goal and plan state without altering canonical fitness data."""
    op.create_table(
        "athlete_goals",
        sa.Column("goal_type", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_athlete_goal_user"),
    )
    op.create_index("ix_athlete_goals_user_id", "athlete_goals", ["user_id"], unique=False)
    op.create_table(
        "next_session_plans",
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("session_purpose", sa.String(length=120), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("recommendation", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("adjustment", sa.JSON(), nullable=True),
        sa.Column("feedback", sa.JSON(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["athlete_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_next_session_plans_goal_id", "next_session_plans", ["goal_id"], unique=False
    )
    op.create_index(
        "ix_next_session_plans_status", "next_session_plans", ["status"], unique=False
    )
    op.create_index(
        "ix_next_session_plans_user_id", "next_session_plans", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Remove only the coaching-loop state introduced by this revision."""
    op.drop_table("next_session_plans")
    op.drop_table("athlete_goals")
