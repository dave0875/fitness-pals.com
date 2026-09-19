"""Regression coverage for the reconciled Alembic migration graph."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models import RefreshTokenSession


ALEMBIC_VERSION_NUM_MAX_LENGTH = 32


def test_revision_ids_fit_production_alembic_version_column():
    """PostgreSQL rejects revision identifiers longer than VARCHAR(32)."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    oversized = {
        revision.revision: len(revision.revision)
        for revision in scripts.walk_revisions()
        if len(revision.revision) > ALEMBIC_VERSION_NUM_MAX_LENGTH
    }
    assert oversized == {}, (
        "Alembic revision IDs must fit alembic_version.version_num VARCHAR(32): "
        f"{oversized}"
    )


def test_migration_branches_have_one_head_after_provider_redirect_uri():
    """Existing branch histories and the coaching-loop migration must converge."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0017_provider_redirect_uri"]
    provider_redirect_revision = scripts.get_revision("0017_provider_redirect_uri")
    assert provider_redirect_revision is not None
    assert provider_redirect_revision.down_revision == "0016_today_plan"
    today_plan_revision = scripts.get_revision("0016_today_plan")
    assert today_plan_revision is not None
    assert today_plan_revision.down_revision == "0015_remove_pulsai"
    removal_revision = scripts.get_revision("0015_remove_pulsai")
    assert removal_revision is not None
    assert removal_revision.down_revision == "0014_refresh_sessions"
    merge_revision = scripts.get_revision("0010_merge_dossier_heads")
    assert merge_revision is not None
    assert set(merge_revision._normalized_down_revisions) == {
        "0008_add_dossiers",
        "0009_add_archive_import_jobs",
    }
    assert scripts.get_revision("0008_add_published_dossiers") is not None
    assert scripts.get_revision("0009_add_archive_import_jobs") is not None
    assert scripts.get_revision("0012_drive_archive_checkpoints") is not None
    assert scripts.get_revision("0013_oidc_identities") is not None
    assert scripts.get_revision("0014_refresh_sessions") is not None


def test_refresh_session_model_has_exact_durable_security_schema():
    """The refresh store persists only lifecycle state, never raw credentials."""
    table = RefreshTokenSession.__table__

    assert list(table.columns.keys()) == [
        "jti",
        "user_id",
        "issued_at",
        "expires_at",
        "consumed_at",
        "revoked_at",
    ]
    assert [column.name for column in table.primary_key.columns] == ["jti"]
    assert {tuple(column.name for column in index.columns) for index in table.indexes} == {
        ("user_id",),
        ("expires_at",),
    }
    foreign_key = next(iter(table.foreign_keys))
    assert foreign_key.target_fullname == "users.id"
    assert foreign_key.ondelete == "CASCADE"
    assert not any("token" in column.name and column.name != "jti" for column in table.columns)
