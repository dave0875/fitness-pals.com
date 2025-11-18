"""add activity dedupe and ingest audit tables

Revision ID: 0003_activity_dedupe
Revises: 0002_multi_tenant_providers
Create Date: 2025-03-07 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0003_activity_dedupe"
down_revision = "0002_multi_tenant_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("sport", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, default="new"),
        sa.Column("fingerprint_hash", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activities_user_id", "activities", ["user_id"])
    op.create_index("ix_activities_start_time", "activities", ["start_time"])
    op.create_index("ix_activities_sport", "activities", ["sport"])
    op.create_index("ix_activities_fingerprint_hash", "activities", ["fingerprint_hash"])

    op.create_table(
        "activity_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_activity_id", sa.String(), nullable=False),
        sa.Column("raw_hash", sa.String(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False, default="new"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("chosen_fields", postgresql.JSONB(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activity_sources_activity_id", "activity_sources", ["activity_id"])
    op.create_index("ix_activity_sources_provider", "activity_sources", ["provider"])

    op.create_table(
        "ingest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_ingest_runs_provider", "ingest_runs", ["provider"])

    op.create_table(
        "ingest_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ingest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingest_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_activity_id", sa.String(), nullable=True),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("fingerprint", postgresql.JSONB(), nullable=True),
        sa.Column("tolerances", postgresql.JSONB(), nullable=True),
        sa.Column("chosen_fields", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingest_decisions_ingest_run_id", "ingest_decisions", ["ingest_run_id"])
    op.create_index("ix_ingest_decisions_user_id", "ingest_decisions", ["user_id"])
    op.create_index("ix_ingest_decisions_provider", "ingest_decisions", ["provider"])
    op.create_index("ix_ingest_decisions_activity_id", "ingest_decisions", ["activity_id"])


def downgrade() -> None:
    op.drop_index("ix_ingest_decisions_activity_id", table_name="ingest_decisions")
    op.drop_index("ix_ingest_decisions_provider", table_name="ingest_decisions")
    op.drop_index("ix_ingest_decisions_user_id", table_name="ingest_decisions")
    op.drop_index("ix_ingest_decisions_ingest_run_id", table_name="ingest_decisions")
    op.drop_table("ingest_decisions")
    op.drop_index("ix_ingest_runs_provider", table_name="ingest_runs")
    op.drop_table("ingest_runs")
    op.drop_index("ix_activity_sources_provider", table_name="activity_sources")
    op.drop_index("ix_activity_sources_activity_id", table_name="activity_sources")
    op.drop_table("activity_sources")
    op.drop_index("ix_activities_fingerprint_hash", table_name="activities")
    op.drop_index("ix_activities_sport", table_name="activities")
    op.drop_index("ix_activities_start_time", table_name="activities")
    op.drop_index("ix_activities_user_id", table_name="activities")
    op.drop_table("activities")
