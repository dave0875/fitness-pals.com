"""Add tenant_id to user_provider_tokens."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_user_provider_tokens_tenant"
down_revision = "0003_activity_dedupe"
branch_labels = None
depends_on = None


def upgrade():
    """Add nullable tenant_id column and index for multi-tenant scoping."""
    op.add_column(
        "user_provider_tokens",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_user_provider_tokens_tenant_id",
        "user_provider_tokens",
        ["tenant_id"],
        unique=False,
    )


def downgrade():
    """Drop tenant_id column and index."""
    op.drop_index("ix_user_provider_tokens_tenant_id", table_name="user_provider_tokens")
    op.drop_column("user_provider_tokens", "tenant_id")
