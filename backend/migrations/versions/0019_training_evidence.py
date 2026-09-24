"""Add provider-neutral canonical whole-training evidence.

Revision ID: 0019_training_evidence
Revises: 0018_activation_intent
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_training_evidence"
down_revision = "0018_activation_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_training_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingest_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("modality", sa.String(), nullable=False),
        sa.Column("provider_sport", sa.String(), nullable=True),
        sa.Column("provider_sub_sport", sa.String(), nullable=True),
        sa.Column("activity_name", sa.String(), nullable=True),
        sa.Column("timer_seconds", sa.Float(), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("moving_seconds", sa.Float(), nullable=True),
        sa.Column("avg_heart_rate", sa.Float(), nullable=True),
        sa.Column("max_heart_rate", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("avg_power", sa.Float(), nullable=True),
        sa.Column("max_power", sa.Float(), nullable=True),
        sa.Column("normalized_power", sa.Float(), nullable=True),
        sa.Column("avg_cadence", sa.Float(), nullable=True),
        sa.Column("max_cadence", sa.Float(), nullable=True),
        sa.Column("aerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("anaerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("structure", sa.JSON(), nullable=True),
        sa.Column("observed_fields", sa.JSON(), nullable=True),
        sa.Column("derived_fields", sa.JSON(), nullable=True),
        sa.Column("field_provenance", sa.JSON(), nullable=True),
        sa.Column("source_provider", sa.String(), nullable=True),
        sa.Column("source_object_id", sa.String(), nullable=True),
        sa.Column("source_object_name", sa.String(), nullable=True),
        sa.Column("source_object_version", sa.String(), nullable=True),
        sa.Column("source_content_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("activity_id", name="uq_activity_training_evidence_activity"),
    )
    op.create_index("ix_activity_training_evidence_activity_id", "activity_training_evidence", ["activity_id"])
    op.create_index("ix_activity_training_evidence_modality", "activity_training_evidence", ["modality"])


def downgrade() -> None:
    op.drop_index("ix_activity_training_evidence_modality", table_name="activity_training_evidence")
    op.drop_index("ix_activity_training_evidence_activity_id", table_name="activity_training_evidence")
    op.drop_table("activity_training_evidence")
