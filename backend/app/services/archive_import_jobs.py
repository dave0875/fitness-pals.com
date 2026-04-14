"""Async archive import job orchestration."""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ArchiveImportJob, User
from app.services.archive_storage import get_archive_storage_client
from app.services.garmin_export_import import import_garmin_export_archive
from app.types import CurrentUserLike


def _get_storage_client():
    return get_archive_storage_client()


def _slugify_filename(filename: str) -> str:
    basename = os.path.basename(filename or "Garmin Export.zip")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-")
    return cleaned or "garmin-export.zip"


def _error_payload(exc: Exception) -> dict[str, Any]:
    detail = getattr(exc, "detail", None)
    status_code = getattr(exc, "status_code", None)
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(detail if detail is not None else exc),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def _job_status_payload(job: ArchiveImportJob) -> dict[str, Any]:
    result = job.result_json or {}
    payload = {
        "job_id": str(job.id),
        "status": job.status,
        "filename": job.filename,
        "size_bytes": job.size_bytes,
    }
    if result.get("dossier_url"):
        payload["dossier_url"] = result["dossier_url"]
    if result.get("dossier_slug"):
        payload["dossier_slug"] = result["dossier_slug"]
    if result.get("activity_count") is not None:
        payload["activity_count"] = result["activity_count"]
    if job.error_json:
        payload["error"] = job.error_json
    return payload


def _owned_job(db: Session, user: CurrentUserLike, job_id: UUID) -> ArchiveImportJob:
    job = (
        db.query(ArchiveImportJob)
        .filter(ArchiveImportJob.id == job_id, ArchiveImportJob.user_id == user.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Archive import job not found")
    return job


def create_archive_import_job(
    db: Session,
    user: CurrentUserLike,
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    """Create a staged archive import job and return its upload plan."""
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Archive size must be greater than zero")

    storage_client = _get_storage_client()
    job = ArchiveImportJob(
        user_id=user.id,
        provider="garmin_export",
        status="upload_pending",
        filename=filename,
        content_type=content_type or "application/zip",
        size_bytes=size_bytes,
        storage_backend=storage_client.storage_backend,
        storage_key=f"garmin-export/{user.id}/{secrets.token_hex(8)}-{_slugify_filename(filename)}",
        upload_token=secrets.token_urlsafe(24) if storage_client.storage_backend == "filesystem" else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    upload = storage_client.create_upload_plan(job)
    job.upload_expires_at = upload.expires_at  # type: ignore[assignment]
    db.commit()
    db.refresh(job)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "upload": {
            "url": upload.url,
            "method": upload.method,
            "headers": upload.headers,
        },
        "complete_url": f"/api/dossiers/import/garmin-export/{job.id}/complete",
        "status_url": f"/api/dossiers/import/garmin-export/{job.id}",
    }


def receive_archive_import_upload(
    db: Session,
    *,
    job_id: UUID,
    token: str,
    content: bytes,
) -> dict[str, Any]:
    """Accept app-mediated upload bytes for the filesystem storage backend."""
    job = db.query(ArchiveImportJob).filter(ArchiveImportJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Archive import job not found")
    if job.storage_backend != "filesystem":
        raise HTTPException(status_code=400, detail="Direct upload endpoint is not enabled")
    if job.status not in {"upload_pending", "uploaded"}:
        raise HTTPException(status_code=409, detail="Archive upload is not accepting data")
    if not token or token != job.upload_token:
        raise HTTPException(status_code=401, detail="Invalid upload token")
    if not content:
        raise HTTPException(status_code=400, detail="Archive upload is empty")

    storage_client = _get_storage_client()
    storage_client.write_bytes(job, content)
    job.status = "uploaded"  # type: ignore[assignment]
    db.commit()
    db.refresh(job)
    return {"job_id": str(job.id), "status": job.status}


def complete_archive_import_job(db: Session, user: CurrentUserLike, job_id: UUID) -> dict[str, Any]:
    """Mark an uploaded archive as ready for worker ingestion."""
    job = _owned_job(db, user, job_id)
    if job.status == "completed":
        return _job_status_payload(job)
    if job.status == "processing":
        return _job_status_payload(job)

    storage_client = _get_storage_client()
    if not storage_client.object_exists(job):
        raise HTTPException(status_code=409, detail="Archive upload is not available yet")

    job.status = "queued"  # type: ignore[assignment]
    job.upload_completed_at = job.upload_completed_at or datetime.now(timezone.utc)  # type: ignore[assignment]
    job.error_json = None  # type: ignore[assignment]
    db.commit()
    db.refresh(job)
    return _job_status_payload(job)


def get_archive_import_job_status(db: Session, user: CurrentUserLike, job_id: UUID) -> dict[str, Any]:
    """Return the current user-facing status for an archive import job."""
    return _job_status_payload(_owned_job(db, user, job_id))


def process_archive_import_job(db: Session, job: ArchiveImportJob) -> dict[str, Any]:
    """Execute one queued archive import job inside the worker runtime."""
    job.status = "processing"  # type: ignore[assignment]
    job.started_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    job.error_json = None  # type: ignore[assignment]
    db.commit()
    db.refresh(job)

    user = db.get(User, job.user_id)
    if user is None:
        job.status = "failed"  # type: ignore[assignment]
        job.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        job.error_json = {"type": "LookupError", "message": "User not found"}  # type: ignore[assignment]
        db.commit()
        db.refresh(job)
        return _job_status_payload(job)

    storage_client = _get_storage_client()
    try:
        archive_bytes = storage_client.read_bytes(job)
        result = import_garmin_export_archive(
            db=db,
            user=user,
            filename=job.filename,
            archive_bytes=archive_bytes,
        )
        job.status = "completed"  # type: ignore[assignment]
        job.result_json = result  # type: ignore[assignment]
        job.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        job.error_json = None  # type: ignore[assignment]
        db.commit()
        db.refresh(job)
        return result
    except Exception as exc:  # pylint: disable=broad-except
        job.status = "failed"  # type: ignore[assignment]
        job.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        job.error_json = _error_payload(exc)  # type: ignore[assignment]
        db.commit()
        db.refresh(job)
        raise


def process_pending_archive_import_jobs(db: Session, limit: int | None = None) -> dict[str, int]:
    """Drain queued archive import jobs from the worker runtime."""
    processed = 0
    failed = 0
    while limit is None or processed < limit:
        job = db.query(ArchiveImportJob).filter(ArchiveImportJob.status == "queued").first()
        if job is None:
            break
        try:
            process_archive_import_job(db, job)
        except Exception:  # pylint: disable=broad-except
            failed += 1
        processed += 1
    return {"processed": processed, "failed": failed}
