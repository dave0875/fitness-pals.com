# pylint: disable=invalid-name,no-member

"""add provider apps and user provider tokens

Revision ID: 0002_multi_tenant_providers
Revises: 0001_init
Create Date: 2025-03-07 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0002_multi_tenant_providers"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create provider app/token tables."""
    op.execute("DROP INDEX IF EXISTS ix_provider_apps_provider")
    op.create_table(
        "provider_apps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("auth_url", sa.String(), nullable=True),
        sa.Column("token_url", sa.String(), nullable=True),
        sa.Column("scopes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_apps_provider_v2", "provider_apps", ["provider"])

    op.create_table(
        "user_provider_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=True),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_provider_tokens_user_id", "user_provider_tokens", ["user_id"]
    )
    op.create_index(
        "ix_user_provider_tokens_provider", "user_provider_tokens", ["provider"]
    )


def downgrade() -> None:
    """Drop provider app/token tables."""
    op.drop_index("ix_user_provider_tokens_provider", table_name="user_provider_tokens")
    op.drop_index("ix_user_provider_tokens_user_id", table_name="user_provider_tokens")
    op.drop_table("user_provider_tokens")
    op.drop_index("ix_provider_apps_provider_v2", table_name="provider_apps")
    op.drop_table("provider_apps")
