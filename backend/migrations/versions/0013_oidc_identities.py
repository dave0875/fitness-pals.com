"""Bind application users to stable OIDC issuer and subject identifiers.

Revision ID: 0013_oidc_identities
Revises: 0012_drive_archive_checkpoints
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_oidc_identities"
down_revision = "0012_drive_archive_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the durable external-identity binding table."""
    op.create_table(
        "oidc_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_oidc_identity_issuer_subject",
        ),
    )
    op.create_index(
        "ix_oidc_identities_user_id",
        "oidc_identities",
        ["user_id"],
    )


def downgrade() -> None:
    """Remove external OIDC identity bindings."""
    op.drop_table("oidc_identities")
