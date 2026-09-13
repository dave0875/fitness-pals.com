"""Persist app refresh-session rotation and revocation state.

Revision ID: 0014_refresh_sessions
Revises: 0013_oidc_identities
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_refresh_sessions"
down_revision = "0013_oidc_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable one-time refresh-session state."""
    op.create_table(
        "refresh_token_sessions",
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        "ix_refresh_token_sessions_user_id",
        "refresh_token_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_token_sessions_expires_at",
        "refresh_token_sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable refresh-session state."""
    op.drop_table("refresh_token_sessions")
