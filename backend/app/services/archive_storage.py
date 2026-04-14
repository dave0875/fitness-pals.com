"""Storage clients for staged archive uploads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from app.config import get_settings


@dataclass
class UploadPlan:
    """Upload target details returned to the browser."""

    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


class ArchiveStorageClient(Protocol):
    """Protocol for staged archive upload storage backends."""

    storage_backend: str

    def create_upload_plan(self, job) -> UploadPlan:
        """Return a signed upload target for the given job."""

    def object_exists(self, job) -> bool:
        """Return True when the uploaded archive is available to process."""

    def read_bytes(self, job) -> bytes:
        """Read the staged archive bytes."""

    def write_bytes(self, job, content: bytes) -> None:
        """Persist uploaded bytes for backends that accept app-mediated uploads."""


class FilesystemArchiveStorage:
    """Filesystem-backed staging used for local environments and tests."""

    storage_backend = "filesystem"

    def __init__(self, root: str, ttl_seconds: int):
        self.root = Path(root)
        self.ttl_seconds = ttl_seconds

    def _path_for(self, job) -> Path:
        return self.root / job.storage_key

    def create_upload_plan(self, job) -> UploadPlan:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        query = urlencode({"token": job.upload_token})
        return UploadPlan(
            url=f"/api/dossiers/import/uploads/{job.id}?{query}",
            method="PUT",
            headers={"Content-Type": job.content_type},
            expires_at=expires_at,
        )

    def object_exists(self, job) -> bool:
        return self._path_for(job).exists()

    def read_bytes(self, job) -> bytes:
        return self._path_for(job).read_bytes()

    def write_bytes(self, job, content: bytes) -> None:
        path = self._path_for(job)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


class GCSArchiveStorage:
    """Google Cloud Storage-backed signed-upload staging."""

    storage_backend = "gcs"

    def __init__(
        self,
        *,
        bucket_name: str,
        ttl_seconds: int,
        credentials_json: str | None = None,
        credentials_file: str | None = None,
    ):
        from google.cloud import storage

        self.ttl_seconds = ttl_seconds
        self.credentials = self._load_credentials(credentials_json, credentials_file)
        self.client = storage.Client(
            project=self.credentials.project_id if self.credentials is not None else None,
            credentials=self.credentials,
        )
        self.bucket = self.client.bucket(bucket_name)

    @staticmethod
    def _load_credentials(credentials_json: str | None, credentials_file: str | None) -> Any:
        from google.oauth2 import service_account

        if credentials_json:
            info = json.loads(credentials_json)
            return service_account.Credentials.from_service_account_info(info)
        if credentials_file:
            return service_account.Credentials.from_service_account_file(credentials_file)
        return None

    def _blob(self, job):
        return self.bucket.blob(job.storage_key)

    def create_upload_plan(self, job) -> UploadPlan:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        blob = self._blob(job)
        url = blob.generate_signed_url(
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

    def object_exists(self, job) -> bool:
        return self._blob(job).exists(self.client)

    def read_bytes(self, job) -> bytes:
        return self._blob(job).download_as_bytes()

    def write_bytes(self, job, content: bytes) -> None:
        self._blob(job).upload_from_string(content, content_type=job.content_type)


def get_archive_storage_client() -> ArchiveStorageClient:
    """Resolve the configured archive storage backend."""
    settings = get_settings()
    backend = (settings.archive_import_storage_backend or "filesystem").lower()
    ttl_seconds = settings.archive_import_upload_url_ttl_seconds

    if backend == "filesystem":
        return FilesystemArchiveStorage(settings.archive_import_filesystem_root, ttl_seconds)
    if backend == "gcs":
        if not settings.archive_import_gcs_bucket:
            raise RuntimeError("Archive import GCS bucket is not configured")
        return GCSArchiveStorage(
            bucket_name=settings.archive_import_gcs_bucket,
            ttl_seconds=ttl_seconds,
            credentials_json=settings.archive_import_gcs_credentials_json,
            credentials_file=settings.archive_import_gcs_credentials_file,
        )
    raise RuntimeError(f"Unsupported archive storage backend: {backend}")
