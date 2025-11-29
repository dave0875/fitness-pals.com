"""Merge multiple heads into a single lineage.

This consolidates the two existing heads:
- 0005_add_user_and_ingest_fk
- 20250309_add_sleep_sessions
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_merge_heads"
down_revision = ("0005_add_user_and_ingest_fk", "20250309_add_sleep_sessions")
branch_labels = None
depends_on = None


def upgrade():
    """No-op merge upgrade."""
    op.execute("SELECT 1")


def downgrade():
    """No-op merge downgrade."""
    op.execute("SELECT 1")
