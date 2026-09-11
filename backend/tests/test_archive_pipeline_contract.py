"""Regression contract for the complete archive-import vertical slice."""

from pathlib import Path

from app.main import app
from app.models import ArchiveImportJob, ArchiveImportObject
from app.workers import sync_jobs_worker


ROOT = Path(__file__).resolve().parents[2]


def test_archive_pipeline_keeps_schema_model_route_worker_and_ui_together():
    """Fail CI if any layer of the restored archive pipeline disappears."""
    migration = ROOT / "backend/migrations/versions/0012_drive_archive_checkpoints.py"
    ui = ROOT / "frontend/pages/import/garmin-archive.js"

    assert migration.exists()
    migration_source = migration.read_text(encoding="utf-8")
    assert "archive_import_jobs" in migration_source
    assert "archive_import_objects" in migration_source
    assert ArchiveImportJob.__tablename__ == "archive_import_jobs"
    assert ArchiveImportObject.__tablename__ == "archive_import_objects"

    paths = {route.path for route in app.routes}
    assert "/api/archive-imports/google-drive" in paths
    assert "/api/archive-imports/uploads/start" in paths
    assert "/api/archive-imports/{job_id}" in paths
    assert callable(sync_jobs_worker.process_pending_archive_import_jobs)

    assert ui.exists()
    ui_source = ui.read_text(encoding="utf-8")
    assert "/api/archive-imports/google-drive" in ui_source
    assert "/api/archive-imports/uploads/start" in ui_source
    assert "status_url" in ui_source
