"""Regression coverage for the reconciled Alembic migration graph."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_dossier_and_archive_import_branches_have_one_merged_head():
    """Existing archive databases and new dossier databases must converge."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0010_merge_dossier_heads"]
    merge_revision = scripts.get_revision("0010_merge_dossier_heads")
    assert merge_revision is not None
    assert set(merge_revision._normalized_down_revisions) == {
        "0008_add_dossiers",
        "0009_add_archive_import_jobs",
    }
    assert scripts.get_revision("0008_add_published_dossiers") is not None
    assert scripts.get_revision("0009_add_archive_import_jobs") is not None
