"""Contract tests for archive import runtime wiring in compose."""

from __future__ import annotations

from pathlib import Path


def test_compose_mounts_shared_archive_import_volume_for_backend_and_worker():
    """Filesystem-backed staged uploads need shared storage between backend and worker."""
    compose_source = Path("compose.yml").read_text()

    assert "archive_imports_data:/tmp/runtrainer-archive-imports" in compose_source
    assert "archive_imports_data:" in compose_source
