"""Safe, read-only availability for athlete archive actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def _valid_service_account_info(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(value.get(key), str) and bool(value[key].strip())
        for key in ("client_email", "private_key", "token_uri")
    )


def archive_capabilities(user: Any, *, settings: Any | None = None) -> dict:
    configured = settings or get_settings()
    try:
        sources = json.loads(configured.google_drive_archive_sources_json or "{}")
    except (TypeError, ValueError):
        sources = None
    source = (
        sources.get(str(getattr(user, "email", "") or "").strip().lower())
        if isinstance(sources, dict)
        else None
    )
    folder = source.get("folder_id") if isinstance(source, dict) else source
    has_folder = isinstance(folder, str) and bool(folder.strip())
    credentials_json = configured.google_drive_service_account_json
    credentials_file = configured.google_drive_service_account_file
    try:
        has_credentials = bool(
            credentials_json
            and _valid_service_account_info(json.loads(credentials_json))
        )
    except (TypeError, ValueError):
        has_credentials = False
    if credentials_file:
        try:
            file_info = json.loads(Path(credentials_file).read_text(encoding="utf-8"))
            has_credentials = has_credentials or _valid_service_account_info(file_info)
        except (OSError, TypeError, ValueError):
            pass

    if not isinstance(sources, dict):
        drive_reason = "Drive source configuration is invalid."
    elif not has_folder:
        drive_reason = "No private Drive folder is assigned to this account."
    elif not has_credentials:
        drive_reason = "Drive service credentials are not configured."
    else:
        drive_reason = None

    storage = configured.archive_import_storage_backend.lower()
    upload_available = storage == "filesystem" or (
        storage == "gcs" and bool(configured.archive_import_gcs_bucket)
    )
    return {
        "drive": {"available": drive_reason is None, "reason": drive_reason},
        "upload": {
            "available": upload_available,
            "reason": None if upload_available else "Archive upload storage is not configured.",
        },
    }
