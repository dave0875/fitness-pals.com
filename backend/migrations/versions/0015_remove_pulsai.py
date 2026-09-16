"""Remove the deprecated PulsAI integration and purge its stored credentials.

Revision ID: 0015_remove_pulsai
Revises: 0014_refresh_sessions
Create Date: 2026-09-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Any

from alembic import context, op
import sqlalchemy as sa


revision = "0015_remove_pulsai"
down_revision = "0014_refresh_sessions"
branch_labels = None
depends_on = None

DEPRECATED_PROVIDER = "pulsai"
CANONICAL_PROVIDER = "garmin"
SENSITIVE_KEYS = {
    "endpoint",
    "endpoint_host",
    "mcp_url",
    "private_url",
}


def _sanitize(value: Any) -> Any:
    """Remove private bridge endpoints and relabel retained Garmin provenance."""
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        if "pulsai.me" in value.lower():
            return "[removed deprecated provider endpoint]"
        return value.replace("PulsAI", "Garmin").replace("pulsai", "garmin")
    return value


def _sanitize_json_columns(
    bind: sa.Connection,
    table_name: str,
    column_names: tuple[str, ...],
) -> None:
    """Sanitize JSON payloads without assuming PostgreSQL-only JSON operators."""
    if not sa.inspect(bind).has_table(table_name):
        return
    table = sa.table(
        table_name,
        sa.column("id"),
        *(sa.column(name, sa.JSON()) for name in column_names),
    )
    rows = bind.execute(sa.select(table)).mappings().all()
    for row in rows:
        changes = {
            name: _sanitize(row[name])
            for name in column_names
            if row[name] is not None
        }
        if changes:
            bind.execute(table.update().where(table.c.id == row["id"]).values(**changes))


def upgrade() -> None:
    """Delete connection secrets and retain imported activity data as Garmin data."""
    if context.is_offline_mode():
        for table_name in (
            "sync_checkpoints",
            "sync_jobs",
            "user_provider_tokens",
            "provider_apps",
        ):
            op.execute(
                f"DELETE FROM {table_name} WHERE provider = '{DEPRECATED_PROVIDER}'"
            )
        for table_name in (
            "activity_sources",
            "ingest_decisions",
            "ingest_runs",
        ):
            op.execute(
                f"UPDATE {table_name} SET provider = '{CANONICAL_PROVIDER}' "
                f"WHERE provider = '{DEPRECATED_PROVIDER}'"
            )
        op.execute(
            "DELETE FROM sleep_sessions WHERE provider = 'pulsai' AND EXISTS ("
            "SELECT 1 FROM sleep_sessions AS canonical "
            "WHERE canonical.user_id = sleep_sessions.user_id "
            "AND canonical.daily_sleep_id = sleep_sessions.daily_sleep_id "
            "AND canonical.provider = 'garmin')"
        )
        op.execute(
            "UPDATE sleep_sessions SET provider = 'garmin' WHERE provider = 'pulsai'"
        )
        return

    bind = op.get_bind()

    # Credentials and obsolete worker state must not survive removal.
    bind.execute(
        sa.text("DELETE FROM sync_checkpoints WHERE provider = :provider"),
        {"provider": DEPRECATED_PROVIDER},
    )
    bind.execute(
        sa.text("DELETE FROM sync_jobs WHERE provider = :provider"),
        {"provider": DEPRECATED_PROVIDER},
    )
    bind.execute(
        sa.text("DELETE FROM user_provider_tokens WHERE provider = :provider"),
        {"provider": DEPRECATED_PROVIDER},
    )
    bind.execute(
        sa.text("DELETE FROM provider_apps WHERE provider = :provider"),
        {"provider": DEPRECATED_PROVIDER},
    )

    # The removed bridge only transported Garmin records. Preserve those records
    # while making Garmin their canonical provenance label.
    for table_name in (
        "activity_sources",
        "ingest_decisions",
        "ingest_runs",
    ):
        if sa.inspect(bind).has_table(table_name):
            bind.execute(
                sa.text(
                    f"UPDATE {table_name} SET provider = :canonical "
                    "WHERE provider = :deprecated"
                ),
                {
                    "canonical": CANONICAL_PROVIDER,
                    "deprecated": DEPRECATED_PROVIDER,
                },
            )

    if sa.inspect(bind).has_table("sleep_sessions"):
        bind.execute(
            sa.text(
                "DELETE FROM sleep_sessions WHERE provider = :deprecated AND EXISTS ("
                "SELECT 1 FROM sleep_sessions AS canonical "
                "WHERE canonical.user_id = sleep_sessions.user_id "
                "AND canonical.daily_sleep_id = sleep_sessions.daily_sleep_id "
                "AND canonical.provider = :canonical)"
            ),
            {
                "canonical": CANONICAL_PROVIDER,
                "deprecated": DEPRECATED_PROVIDER,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE sleep_sessions SET provider = :canonical "
                "WHERE provider = :deprecated"
            ),
            {
                "canonical": CANONICAL_PROVIDER,
                "deprecated": DEPRECATED_PROVIDER,
            },
        )

    for table_name in ("activity_sources", "ingest_decisions"):
        if sa.inspect(bind).has_table(table_name):
            bind.execute(
                sa.text(
                    f"UPDATE {table_name} "
                    "SET reason = replace(replace(reason, 'PulsAI', 'Garmin'), "
                    "'pulsai', 'garmin') WHERE reason IS NOT NULL"
                )
            )

    for table_name, columns in (
        ("activities", ("metadata",)),
        ("activity_sources", ("chosen_fields", "raw_payload")),
        ("ingest_runs", ("summary",)),
        ("ingest_decisions", ("fingerprint", "tolerances", "chosen_fields")),
        ("sleep_sessions", ("summary_json",)),
        ("conversations", ("metadata",)),
        ("dossier_jobs", ("request", "error")),
        ("dossier_artifacts", ("content",)),
    ):
        _sanitize_json_columns(bind, table_name, columns)


def downgrade() -> None:
    """Credential deletion is intentionally irreversible."""
