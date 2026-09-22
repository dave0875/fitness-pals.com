"""Phase 6 trust contracts that should remain true behind athlete Settings."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.archive_capabilities import archive_capabilities


def test_archive_capabilities_expose_availability_without_service_secrets():
    """Athlete capability responses must never serialize service-account material."""
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret-material\n-----END PRIVATE KEY-----\n"
    settings = SimpleNamespace(
        google_drive_archive_sources_json=json.dumps(
            {"athlete@example.com": {"folder_id": "drive-folder-id"}}
        ),
        google_drive_service_account_json=json.dumps(
            {
                "client_email": "archive-reader@example.iam.gserviceaccount.com",
                "private_key": private_key,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        google_drive_service_account_file=None,
        archive_import_storage_backend="filesystem",
        archive_import_gcs_bucket=None,
    )
    user = SimpleNamespace(email="athlete@example.com")

    result = archive_capabilities(user, settings=settings)
    serialized = repr(result)

    assert result == {
        "drive": {"available": True, "reason": None},
        "upload": {"available": True, "reason": None},
    }
    assert private_key not in serialized
    assert "archive-reader@example.iam.gserviceaccount.com" not in serialized
    assert "drive-folder-id" not in serialized
