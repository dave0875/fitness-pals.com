"""Asynchronous, athlete-owned archive import orchestration."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ArchiveImportJob, ArchiveImportObject, User
from app.services.archive_storage import get_archive_storage_client
from app.services.garmin_archive_import import ingest_archive_object
from app.services.google_drive_archive import GoogleDriveArchiveClient
from app.services.google_drive_archive import DriveArchiveObject


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _storage_client():
    return get_archive_storage_client()


def _drive_client():
    return GoogleDriveArchiveClient()


def _slugify_filename(filename: str) -> str:
    basename = os.path.basename(filename or "Garmin Export.zip")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-") or "garmin-export.zip"


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(getattr(exc, "detail", exc))}


def _owned_job(db: Session, user: Any, job_id: UUID) -> ArchiveImportJob:
    job = (
        db.query(ArchiveImportJob)
        .filter(ArchiveImportJob.id == job_id, ArchiveImportJob.user_id == user.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Archive import job not found")
    return job


def _job_payload(job: ArchiveImportJob) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": str(job.id),
        "status": job.status,
        "source_type": job.source_type,
        "filename": job.filename,
        "status_url": f"/api/archive-imports/{job.id}",
    }
    if job.result_json:
        payload.update(job.result_json)
    if job.error_json:
        payload["error"] = job.error_json
    return payload


def create_drive_import_job(
    db: Session,
    user: Any,
    *,
    folder_id: str,
    authorization: str = "service_account",
) -> ArchiveImportJob:
    """Queue an athlete-bound Drive source without accepting a client locator."""
    now = _now()
    job = ArchiveImportJob(
        user_id=user.id,
        provider="garmin_archive",
        source_type="google_drive",
        source_locator=folder_id,
        source_metadata_json={"folder_id": folder_id, "authorization": authorization},
        status="queued",
        filename="Google Drive Garmin archive",
        content_type="application/vnd.google-apps.folder",
        size_bytes=0,
        storage_backend="google_drive",
        storage_key=f"google-drive/{user.id}/{secrets.token_hex(12)}",
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_upload_import_job(
    db: Session,
    user: Any,
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    """Create a staged upload while keeping large bytes out of the request route."""
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Archive size must be greater than zero")
    storage = _storage_client()
    now = _now()
    job = ArchiveImportJob(
        user_id=user.id,
        provider="garmin_archive",
        source_type="upload",
        source_locator=None,
        source_metadata_json=None,
        status="upload_pending",
        filename=filename,
        content_type=content_type or "application/zip",
        size_bytes=size_bytes,
        storage_backend=storage.storage_backend,
        storage_key=(
            f"garmin-archive/{user.id}/{secrets.token_hex(8)}-{_slugify_filename(filename)}"
        ),
        upload_token=(
            secrets.token_urlsafe(24) if storage.storage_backend == "filesystem" else None
        ),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    plan = storage.create_upload_plan(job)
    job.upload_expires_at = plan.expires_at
    job.updated_at = _now()
    db.commit()
    return {
        **_job_payload(job),
        "upload": {"url": plan.url, "method": plan.method, "headers": plan.headers},
        "complete_url": f"/api/archive-imports/uploads/{job.id}/complete",
    }


def receive_upload(
    db: Session, *, job_id: UUID, token: str, content: bytes
) -> dict[str, Any]:
    """Receive bytes only with the unguessable job upload token."""
    job = db.query(ArchiveImportJob).filter(ArchiveImportJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Archive import job not found")
    if job.source_type != "upload" or job.status not in {"upload_pending", "uploaded"}:
        raise HTTPException(status_code=409, detail="Archive upload is not accepting data")
    if job.storage_backend != "filesystem":
        raise HTTPException(status_code=409, detail="Archive uses a direct storage upload")
    if not token or not secrets.compare_digest(token, job.upload_token or ""):
        raise HTTPException(status_code=401, detail="Invalid upload token")
    if not content or len(content) != job.size_bytes:
        raise HTTPException(status_code=400, detail="Archive upload size does not match request")
    _storage_client().write_bytes(job, content)
    job.status = "uploaded"
    job.updated_at = _now()
    db.commit()
    return _job_payload(job)


def complete_upload(db: Session, user: Any, job_id: UUID) -> dict[str, Any]:
    job = _owned_job(db, user, job_id)
    if job.source_type != "upload":
        raise HTTPException(status_code=409, detail="Job is not an uploaded archive")
    if not _storage_client().object_exists(job):
        raise HTTPException(status_code=409, detail="Archive upload is not available")
    job.status = "queued"
    job.upload_completed_at = job.upload_completed_at or _now()
    job.updated_at = _now()
    job.error_json = None
    db.commit()
    return _job_payload(job)


def get_archive_import_job_status(db: Session, user: Any, job_id: UUID) -> dict[str, Any]:
    return _job_payload(_owned_job(db, user, job_id))


def latest_archive_import_job_status(db: Session, user: Any) -> dict[str, Any] | None:
    """Return the latest owned job so the UI can resume progress after navigation."""
    job = (
        db.query(ArchiveImportJob)
        .filter(ArchiveImportJob.user_id == user.id)
        .order_by(ArchiveImportJob.created_at.desc())
        .first()
    )
    if job is None or getattr(job, "user_id", None) != user.id:
        return None
    return _job_payload(job)


def _existing_checkpoint(
    db: Session, job: ArchiveImportJob, source: DriveArchiveObject
) -> ArchiveImportObject | None:
    return (
        db.query(ArchiveImportObject)
        .filter(
            ArchiveImportObject.user_id == job.user_id,
            ArchiveImportObject.provider == job.provider,
            ArchiveImportObject.source_type == job.source_type,
            ArchiveImportObject.source_object_id == source.object_id,
            ArchiveImportObject.source_version == source.version,
        )
        .first()
    )


def _process_object(
    db: Session,
    job: ArchiveImportJob,
    source: DriveArchiveObject,
    content_loader: Callable[[], bytes],
) -> tuple[str, int]:
    checkpoint = _existing_checkpoint(db, job, source)
    if checkpoint is not None and checkpoint.status == "completed":
        return "skipped", 0
    now = _now()
    if checkpoint is None:
        checkpoint = ArchiveImportObject(
            job_id=job.id,
            user_id=job.user_id,
            provider=job.provider,
            source_type=job.source_type,
            source_object_id=source.object_id,
            source_version=source.version,
            object_name=source.name,
            content_type=source.mime_type,
            size_bytes=source.size_bytes,
            status="processing",
            created_at=now,
            updated_at=now,
        )
        db.add(checkpoint)
    else:
        checkpoint.job_id = job.id
        checkpoint.status = "processing"
        checkpoint.error_json = None
        checkpoint.updated_at = now
    db.commit()
    try:
        content = content_loader()
        result = ingest_archive_object(
            db=db, user=db.get(User, job.user_id), source_object=source, content=content
        )
        checkpoint.status = "completed"
        checkpoint.processed_at = _now()
        checkpoint.result_json = result
        checkpoint.error_json = None
        checkpoint.updated_at = _now()
        db.commit()
        return "imported", int(result.get("activity_count") or 0)
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error_json = _error_payload(exc)
        checkpoint.processed_at = _now()
        checkpoint.updated_at = _now()
        db.commit()
        return "failed", 0


def process_archive_import_job(db: Session, job: ArchiveImportJob) -> dict[str, Any]:
    """Process all objects, committing a durable checkpoint after each one."""
    user = db.get(User, job.user_id)
    if user is None:
        raise LookupError("Archive import athlete no longer exists")
    job.status = "processing"
    job.started_at = _now()
    job.updated_at = _now()
    job.error_json = None
    db.commit()

    downloads: Any
    if job.source_type == "google_drive":
        authorization = (job.source_metadata_json or {}).get("authorization")
        drive = (
            GoogleDriveArchiveClient.for_user(db, user)
            if authorization == "user_oauth"
            else _drive_client()
        )
        objects = drive.list_supported_objects(job.source_locator or "")
        downloads = ((item, lambda item=item: drive.download(item)) for item in objects)
    elif job.source_type == "upload":
        content = _storage_client().read_bytes(job)
        version = hashlib.sha256(content).hexdigest()
        item = DriveArchiveObject(
            object_id=f"upload:{job.storage_key}",
            name=job.filename,
            mime_type=job.content_type,
            version=version,
            modified_time=None,
            size_bytes=job.size_bytes,
        )
        downloads = ((item, lambda: content),)
    else:
        raise ValueError(f"Unsupported archive source: {job.source_type}")

    summary = {"objects_imported": 0, "objects_skipped": 0, "objects_failed": 0, "activities": 0}
    for source, content_loader in downloads:
        outcome, activity_count = _process_object(db, job, source, content_loader)
        summary[f"objects_{outcome}"] += 1
        summary["activities"] += activity_count

    job.result_json = summary
    job.finished_at = _now()
    job.updated_at = _now()
    if summary["objects_failed"]:
        job.status = "failed"
        job.error_json = {
            "type": "ArchiveObjectError",
            "message": f"{summary['objects_failed']} archive object(s) failed",
        }
    else:
        job.status = "completed"
    db.commit()
    return summary


def process_pending_archive_import_jobs(db: Session, limit: int | None = None) -> dict[str, int]:
    processed = 0
    failed = 0
    while limit is None or processed < limit:
        job = db.query(ArchiveImportJob).filter(ArchiveImportJob.status == "queued").first()
        if job is None:
            break
        try:
            process_archive_import_job(db, job)
            failed += int(job.status == "failed")
        except Exception as exc:
            job.status = "failed"
            job.error_json = _error_payload(exc)
            job.finished_at = _now()
            job.updated_at = _now()
            db.commit()
            failed += 1
        processed += 1
    return {"processed": processed, "failed": failed}
