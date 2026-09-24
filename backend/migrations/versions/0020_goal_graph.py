"""Add canonical athlete Goal Graph event and objective nodes.

Revision ID: 0020_goal_graph
Revises: 0019_training_evidence
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_goal_graph"
down_revision = "0019_training_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create graph nodes and faithfully project existing event-like goal intent."""
    op.create_table(
        "athlete_goal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("athlete_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("distance_label", sa.String(length=80), nullable=True),
        sa.Column("target_performance", sa.String(length=120), nullable=True),
        sa.Column("target_time_seconds", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=24), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_athlete_goal_events_user_id", ["user_id"]),
        ("ix_athlete_goal_events_goal_id", ["goal_id"]),
        ("ix_athlete_goal_events_role", ["role"]),
        ("ix_athlete_goal_events_event_date", ["event_date"]),
        ("ix_athlete_goal_events_lifecycle_state", ["lifecycle_state"]),
    ):
        op.create_index(name, "athlete_goal_events", columns)

    op.create_table(
        "athlete_goal_objectives",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("athlete_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("athlete_goal_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=24), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_athlete_goal_objectives_user_id", ["user_id"]),
        ("ix_athlete_goal_objectives_goal_id", ["goal_id"]),
        ("ix_athlete_goal_objectives_event_id", ["event_id"]),
        ("ix_athlete_goal_objectives_target_date", ["target_date"]),
        ("ix_athlete_goal_objectives_lifecycle_state", ["lifecycle_state"]),
    ):
        op.create_index(name, "athlete_goal_objectives", columns)

    # Offline SQL generation cannot execute SELECTs and returns no Result object.
    # Production/live upgrades still run the faithful compatibility backfill below.
    if op.get_context().as_sql:
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, goal_type, target_date, intent, created_at, updated_at "
            "FROM athlete_goals"
        )
    ).mappings()
    event_table = sa.table(
        "athlete_goal_events",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("goal_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()), sa.column("event_type", sa.String()),
        sa.column("label", sa.String()), sa.column("event_date", sa.Date()),
        sa.column("distance_label", sa.String()), sa.column("target_performance", sa.String()),
        sa.column("target_time_seconds", sa.Integer()), sa.column("priority", sa.Integer()),
        sa.column("lifecycle_state", sa.String()), sa.column("provenance", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    backfill = []
    for row in rows:
        details = row["intent"] if isinstance(row["intent"], dict) else {}
        target_time = details.get("target_time_seconds")
        if isinstance(target_time, bool) or not isinstance(target_time, int) or target_time <= 0:
            target_time = None
        if not any(
            value not in (None, "")
            for value in (
                row["target_date"], details.get("target_distance"),
                details.get("target_performance"), target_time,
            )
        ):
            continue
        explicit_fields = ["event.type", "event.role"]
        if row["target_date"] is not None:
            explicit_fields.append("event.date")
        if details.get("target_distance"):
            explicit_fields.append("target.distance")
        if details.get("target_performance"):
            explicit_fields.append("target.performance")
        if target_time is not None:
            explicit_fields.append("target.time_seconds")
        now = datetime.now(timezone.utc)
        backfill.append({
            "id": uuid.uuid4(), "user_id": row["user_id"], "goal_id": row["id"],
            "role": "primary", "event_type": row["goal_type"], "label": None,
            "event_date": row["target_date"], "distance_label": details.get("target_distance"),
            "target_performance": details.get("target_performance"),
            "target_time_seconds": target_time, "priority": 1, "lifecycle_state": "planned",
            "provenance": {
                "kind": "explicit", "source": "phase4_migration", "basis": "athlete_goal",
                "canonical_model": "athlete_goal", "record_id": str(row["id"]),
                "explicit_fields": explicit_fields,
            },
            "created_at": row["created_at"] or now, "updated_at": row["updated_at"] or now,
        })
    if backfill:
        op.bulk_insert(event_table, backfill)


def downgrade() -> None:
    """Remove only Goal Graph child nodes; the compatibility root remains intact."""
    for name in (
        "ix_athlete_goal_objectives_lifecycle_state", "ix_athlete_goal_objectives_target_date",
        "ix_athlete_goal_objectives_event_id", "ix_athlete_goal_objectives_goal_id",
        "ix_athlete_goal_objectives_user_id",
    ):
        op.drop_index(name, table_name="athlete_goal_objectives")
    op.drop_table("athlete_goal_objectives")
    for name in (
        "ix_athlete_goal_events_lifecycle_state", "ix_athlete_goal_events_event_date",
        "ix_athlete_goal_events_role", "ix_athlete_goal_events_goal_id",
        "ix_athlete_goal_events_user_id",
    ):
        op.drop_index(name, table_name="athlete_goal_events")
    op.drop_table("athlete_goal_events")
