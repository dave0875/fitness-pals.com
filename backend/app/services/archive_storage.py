"""Storage backends for staged Garmin archive uploads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from app.config import get_settings


@dataclass(frozen=True)
class UploadPlan:
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


class ArchiveStorageClient(Protocol):
    storage_backend: str

    def create_upload_plan(self, job) -> UploadPlan: ...
    def write_bytes(self, job, content: bytes) -> None: ...
    def read_bytes(self, job) -> bytes: ...
    def object_exists(self, job) -> bool: ...


class FilesystemArchiveStorage:
    storage_backend = "filesystem"

    def __init__(self, root: str, ttl_seconds: int):
        self.root = Path(root)
        self.ttl_seconds = ttl_seconds

    def _path(self, job) -> Path:
        candidate = (self.root / job.storage_key).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ValueError("Invalid archive storage key")
        return candidate

    def create_upload_plan(self, job) -> UploadPlan:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        query = urlencode({"token": job.upload_token})
        return UploadPlan(
            url=f"/api/archive-imports/uploads/{job.id}?{query}",
            method="PUT",
            headers={"Content-Type": job.content_type},
            expires_at=expires_at,
        )

    def write_bytes(self, job, content: bytes) -> None:
        target = self._path(job)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def read_bytes(self, job) -> bytes:
        return self._path(job).read_bytes()

    def object_exists(self, job) -> bool:
        return self._path(job).is_file()


class GCSArchiveStorage:
    """Production staging with a browser-to-GCS V4 signed upload URL."""

    storage_backend = "gcs"

    def __init__(
        self,
        *,
        bucket_name: str,
        ttl_seconds: int,
        credentials_json: str | None,
        credentials_file: str | None,
    ):
        from google.cloud import storage
        from google.oauth2 import service_account

        credentials: Any = None
        if credentials_json:
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(credentials_json)
            )
        elif credentials_file:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file
            )
        self.ttl_seconds = ttl_seconds
        self.client = storage.Client(
            project=getattr(credentials, "project_id", None), credentials=credentials
        )
        self.bucket = self.client.bucket(bucket_name)

    def _blob(self, job):
        return self.bucket.blob(job.storage_key)

    def create_upload_plan(self, job) -> UploadPlan:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        url = self._blob(job).generate_signed_url(
            version="v4",
            expiration=expires_at,
            method="PUT",
            content_type=job.content_type,
        )
        return UploadPlan(
            url=url,
            method="PUT",
            headers={"Content-Type": job.content_type},
            expires_at=expires_at,
        )

    def write_bytes(self, job, content: bytes) -> None:
        self._blob(job).upload_from_string(content, content_type=job.content_type)

    def read_bytes(self, job) -> bytes:
        return self._blob(job).download_as_bytes()

    def object_exists(self, job) -> bool:
        return self._blob(job).exists(self.client)


def get_archive_storage_client() -> ArchiveStorageClient:
    settings = get_settings()
    backend = settings.archive_import_storage_backend.lower()
    if backend == "filesystem":
        return FilesystemArchiveStorage(
            settings.archive_import_filesystem_root,
            settings.archive_import_upload_url_ttl_seconds,
        )
    if backend == "gcs":
        if not settings.archive_import_gcs_bucket:
            raise RuntimeError("Archive import GCS bucket is not configured")
        return GCSArchiveStorage(
            bucket_name=settings.archive_import_gcs_bucket,
            ttl_seconds=settings.archive_import_upload_url_ttl_seconds,
            credentials_json=settings.archive_import_gcs_credentials_json,
            credentials_file=settings.archive_import_gcs_credentials_file,
        )
    raise RuntimeError(f"Unsupported archive storage backend: {backend}")
