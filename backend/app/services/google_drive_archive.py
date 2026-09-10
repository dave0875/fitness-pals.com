"""Read-only Google Drive adapter for configured athlete archive folders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.config import get_settings


DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveArchiveObject:
    """Stable metadata needed to checkpoint and download one Drive object."""

    object_id: str
    name: str
    mime_type: str
    version: str
    modified_time: str | None
    size_bytes: int


def _normal_email(value: Any) -> str:
    return str(value or "").strip().lower()


def configured_folder_for_user(user: Any, *, settings: Any | None = None) -> str:
    """Resolve a folder from the server-side email mapping, never request input."""
    configured = settings or get_settings()
    try:
        sources = json.loads(configured.google_drive_archive_sources_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Google Drive archive sources are invalid") from exc
    if not isinstance(sources, dict):
        raise HTTPException(status_code=503, detail="Google Drive archive sources are invalid")
    source = sources.get(_normal_email(getattr(user, "email", None)))
    folder_id = source.get("folder_id") if isinstance(source, dict) else source
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise HTTPException(
            status_code=404,
            detail="Google Drive archive is not configured for this athlete",
        )
    return folder_id.strip()


def _credentials(settings: Any):
    info = None
    if settings.google_drive_service_account_json:
        try:
            info = json.loads(settings.google_drive_service_account_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google Drive service account JSON is invalid") from exc
    if info:
        return service_account.Credentials.from_service_account_info(
            info, scopes=[DRIVE_READONLY_SCOPE]
        )
    if settings.google_drive_service_account_file:
        credential_path = Path(settings.google_drive_service_account_file)
        return service_account.Credentials.from_service_account_file(
            str(credential_path), scopes=[DRIVE_READONLY_SCOPE]
        )
    raise RuntimeError("Google Drive service account credentials are not configured")


class GoogleDriveArchiveClient:
    """Small Drive v3 client limited to listing and downloading archive objects."""

    def __init__(self, *, settings: Any | None = None, http_client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self.credentials = _credentials(self.settings)
        self.http = http_client or httpx.Client(timeout=60.0)

    def _headers(self) -> dict[str, str]:
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return {"Authorization": f"Bearer {self.credentials.token}"}

    def _children(self, folder_id: str) -> list[dict[str, Any]]:
        page_token = None
        children: list[dict[str, Any]] = []
        while True:
            params: dict[str, str | int] = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": (
                    "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)"
                ),
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self.http.get(
                f"{DRIVE_API}/files", params=params, headers=self._headers()
            )
            response.raise_for_status()
            payload = response.json()
            children.extend(payload.get("files") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return children

    @staticmethod
    def _supported(item: dict[str, Any]) -> bool:
        name = str(item.get("name") or "").lower()
        mime_type = str(item.get("mimeType") or "")
        return (
            name.endswith(".fit")
            or name.endswith(".zip")
            or name.endswith("_summarizedactivities.json")
            or mime_type in {"application/fits", "application/zip"}
        )

    def list_supported_objects(self, folder_id: str) -> list[DriveArchiveObject]:
        """Walk a configured folder and return importable objects deterministically."""
        pending = [folder_id]
        visited: set[str] = set()
        objects: list[DriveArchiveObject] = []
        maximum = int(self.settings.google_drive_archive_max_objects)
        while pending:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for item in self._children(current):
                if item.get("mimeType") == FOLDER_MIME_TYPE:
                    pending.append(str(item["id"]))
                    continue
                if not self._supported(item):
                    continue
                version = str(item.get("md5Checksum") or item.get("modifiedTime") or item["id"])
                objects.append(
                    DriveArchiveObject(
                        object_id=str(item["id"]),
                        name=str(item.get("name") or item["id"]),
                        mime_type=str(item.get("mimeType") or "application/octet-stream"),
                        version=version,
                        modified_time=item.get("modifiedTime"),
                        size_bytes=int(item.get("size") or 0),
                    )
                )
                if len(objects) > maximum:
                    raise RuntimeError("Google Drive archive exceeds configured object limit")
        return sorted(objects, key=lambda item: (item.modified_time or "", item.name, item.object_id))

    def download(self, item: DriveArchiveObject) -> bytes:
        response = self.http.get(
            f"{DRIVE_API}/files/{item.object_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.content
