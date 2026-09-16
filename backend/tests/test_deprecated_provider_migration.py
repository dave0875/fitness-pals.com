"""Regression coverage for removal of the deprecated provider bridge."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def test_deprecated_provider_is_absent_from_runtime_surfaces():
    """Runtime code, deployment configuration, and product copy stay bridge-free."""
    repository_root = Path(__file__).resolve().parents[2]
    deprecated_name = "pul" + "sai"
    candidates = [
        *repository_root.glob("backend/app/**/*.py"),
        *repository_root.glob("frontend/pages/**/*.js"),
        repository_root / "backend" / "requirements.txt",
        repository_root / "compose.yml",
        repository_root / "README.md",
    ]

    offenders = [
        str(path.relative_to(repository_root))
        for path in candidates
        if path.is_file() and deprecated_name in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0015_remove_pulsai.py"
    )
    spec = importlib.util.spec_from_file_location("remove_deprecated_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_purges_bridge_credentials_and_keeps_garmin_records(monkeypatch):
    """The one-way cleanup removes secrets while retaining canonical activity data."""
    migration = _load_migration()
    metadata = sa.MetaData()
    for name in ("sync_checkpoints", "sync_jobs", "user_provider_tokens", "provider_apps"):
        sa.Table(
            name,
            metadata,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("provider", sa.String(), nullable=False),
        )
    activities = sa.Table(
        "activities",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("metadata", sa.JSON()),
    )
    sources = sa.Table(
        "activity_sources",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("reason", sa.String()),
        sa.Column("chosen_fields", sa.JSON()),
        sa.Column("raw_payload", sa.JSON()),
    )
    sleep_sessions = sa.Table(
        "sleep_sessions",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("daily_sleep_id", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON()),
        sa.UniqueConstraint("user_id", "provider", "daily_sleep_id"),
    )

    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        for table_name in (
            "sync_checkpoints",
            "sync_jobs",
            "user_provider_tokens",
            "provider_apps",
        ):
            table = metadata.tables[table_name]
            connection.execute(
                table.insert(),
                [
                    {"id": f"deprecated-{table_name}", "provider": "pulsai"},
                    {"id": f"garmin-{table_name}", "provider": "garmin"},
                ],
            )
        connection.execute(
            activities.insert(),
            {
                "id": "activity-1",
                "metadata": {
                    "source_provider": "pulsai",
                    "private_url": "https://private.pulsai.me/secret",
                },
            },
        )
        connection.execute(
            sources.insert(),
            {
                "id": "source-1",
                "provider": "pulsai",
                "reason": "Garmin data delivered through PulsAI",
                "chosen_fields": {
                    "source_provider": "pulsai",
                    "endpoint_host": "private.pulsai.me",
                },
                "raw_payload": {"private_url": "https://private.pulsai.me/secret"},
            },
        )
        connection.execute(
            sleep_sessions.insert(),
            [
                {
                    "id": "sleep-garmin",
                    "user_id": "user-1",
                    "provider": "garmin",
                    "daily_sleep_id": 20260909,
                    "summary_json": {"source_provider": "garmin"},
                },
                {
                    "id": "sleep-duplicate",
                    "user_id": "user-1",
                    "provider": "pulsai",
                    "daily_sleep_id": 20260909,
                    "summary_json": {"source_provider": "pulsai"},
                },
                {
                    "id": "sleep-legacy-only",
                    "user_id": "user-1",
                    "provider": "pulsai",
                    "daily_sleep_id": 20260908,
                    "summary_json": {"source_provider": "pulsai"},
                },
            ],
        )

        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
        migration.upgrade()

        for table_name in (
            "sync_checkpoints",
            "sync_jobs",
            "user_provider_tokens",
            "provider_apps",
        ):
            providers = connection.execute(
                sa.select(metadata.tables[table_name].c.provider)
            ).scalars().all()
            assert providers == ["garmin"]

        activity_metadata = connection.execute(
            sa.select(activities.c.metadata)
        ).scalar_one()
        assert activity_metadata == {"source_provider": "garmin"}

        source = connection.execute(sa.select(sources)).mappings().one()
        assert source["provider"] == "garmin"
        assert source["reason"] == "Garmin data delivered through Garmin"
        assert source["chosen_fields"] == {"source_provider": "garmin"}
        assert source["raw_payload"] == {}

        sleep_rows = connection.execute(
            sa.select(
                sleep_sessions.c.id,
                sleep_sessions.c.provider,
                sleep_sessions.c.summary_json,
            ).order_by(sleep_sessions.c.id)
        ).mappings().all()
        assert [row["id"] for row in sleep_rows] == [
            "sleep-garmin",
            "sleep-legacy-only",
        ]
        assert all(row["provider"] == "garmin" for row in sleep_rows)
        assert all(
            row["summary_json"]["source_provider"] == "garmin"
            for row in sleep_rows
        )
