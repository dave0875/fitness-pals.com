"""Regression coverage for the reconciled Alembic migration graph."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


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


def test_migration_branches_have_one_head_after_user_roles():
    """Existing branch histories and the user-role migration must converge."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0012_drive_archive_checkpoints"]
    merge_revision = scripts.get_revision("0010_merge_dossier_heads")
    assert merge_revision is not None
    assert set(merge_revision._normalized_down_revisions) == {
        "0008_add_dossiers",
        "0009_add_archive_import_jobs",
    }
    assert scripts.get_revision("0008_add_published_dossiers") is not None
    assert scripts.get_revision("0009_add_archive_import_jobs") is not None
    assert scripts.get_revision("0012_drive_archive_checkpoints") is not None
