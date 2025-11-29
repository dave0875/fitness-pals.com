# pylint: disable=invalid-name
"""Add user linkage to ingest runs and activities, seed historical ingest run

Revision ID: 0005_add_user_and_ingest_fk
Revises: 0004_user_provider_tokens_tenant
Create Date: 2025-11-21 00:00:00.000000
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_add_user_and_ingest_fk"
down_revision = "0004_user_provider_tokens_tenant"
branch_labels = None
depends_on = None


def upgrade():
    dialect_name = context.get_context().dialect.name
    is_sqlite = dialect_name.startswith("sqlite")

    op.add_column(
        "ingest_runs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("ingest_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ingest_runs_user_provider", "ingest_runs", ["user_id", "provider", "started_at"])
    op.create_index("ix_activities_user_start_time", "activities", ["user_id", "start_time"])

    # In offline (--sql) runs, skip FK creation to avoid SQLite reflection requirements.
    if context.is_offline_mode():
        return

    if is_sqlite:
        # SQLite needs batch alterations for foreign keys when running offline/online.
        with op.batch_alter_table("ingest_runs") as batch_op:
            batch_op.create_foreign_key(
                "fk_ingest_runs_user",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
        with op.batch_alter_table("activities") as batch_op:
            batch_op.create_foreign_key(
                "fk_activities_ingest_run",
                "ingest_runs",
                ["ingest_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            "fk_ingest_runs_user",
            source_table="ingest_runs",
            referent_table="users",
            local_cols=["user_id"],
            remote_cols=["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_activities_ingest_run",
            source_table="activities",
            referent_table="ingest_runs",
            local_cols=["ingest_run_id"],
            remote_cols=["id"],
            ondelete="SET NULL",
        )

    conn = op.get_bind()

    # Offline mode ( --sql ) has no real connection; skip data backfill/seed in that case.
    if conn is None or context.is_offline_mode():
        return

    # Resolve the canonical user (dave0875@gmail.com) if present.
    user_id = None
    res = conn.execute(sa.text("SELECT id FROM users WHERE email=:email LIMIT 1"), {"email": "dave0875@gmail.com"})
    row = res.fetchone()
    if row:
        user_id = row[0]

    # Backfill existing ingest_runs with the resolved user_id.
    if user_id:
        conn.execute(sa.text("UPDATE ingest_runs SET user_id=:uid WHERE user_id IS NULL"), {"uid": user_id})

    # Seed a fabricated ingest run to anchor historical Influx points.
    fabricated_run_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    fabricated_ts = datetime(2025, 11, 19, 13, 47, 54, tzinfo=timezone.utc)
    summary_json = json.dumps({"note": "Historical Influx backfill anchor"})
    conn.execute(
        sa.text(
            """
            INSERT INTO ingest_runs (id, user_id, provider, status, started_at, finished_at, summary)
            VALUES (:id, :uid, :prov, :status, :started, :finished, CAST(:summary AS jsonb))
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": str(fabricated_run_id),
            "uid": str(user_id) if user_id else None,
            "prov": "garmin",
            "status": "completed",
            "started": fabricated_ts,
            "finished": fabricated_ts,
            "summary": summary_json,
        },
    )


def downgrade():
    op.drop_constraint("fk_activities_ingest_run", "activities", type_="foreignkey")
    op.drop_constraint("fk_ingest_runs_user", "ingest_runs", type_="foreignkey")
    op.drop_index("ix_activities_user_start_time", table_name="activities")
    op.drop_index("ix_ingest_runs_user_provider", table_name="ingest_runs")
    op.drop_column("activities", "ingest_run_id")
    op.drop_column("ingest_runs", "user_id")
