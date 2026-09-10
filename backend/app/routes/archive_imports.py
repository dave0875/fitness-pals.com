"""Authenticated routes for asynchronous Garmin archive imports."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services import archive_import_jobs
from app.services.google_drive_archive import configured_folder_for_user
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/archive-imports", tags=["archive-imports"])


class UploadStartRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/zip", max_length=255)
    size_bytes: int = Field(gt=0)


@router.post("/google-drive", status_code=status.HTTP_202_ACCEPTED)
def start_google_drive_import(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue the Drive folder assigned to this athlete by server configuration."""
    folder_id = configured_folder_for_user(user)
    job = archive_import_jobs.create_drive_import_job(db, user, folder_id=folder_id)
    return archive_import_jobs.get_archive_import_job_status(db, user, UUID(str(job.id)))


@router.post("/uploads/start")
def start_upload_import(
    payload: UploadStartRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return archive_import_jobs.create_upload_import_job(
        db,
        user,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )


@router.put("/uploads/{job_id}")
async def upload_archive(job_id: UUID, request: Request, token: str, db: Session = Depends(get_db)):
    return archive_import_jobs.receive_upload(
        db, job_id=job_id, token=token, content=await request.body()
    )


@router.post("/uploads/{job_id}/complete", status_code=status.HTTP_202_ACCEPTED)
def complete_upload_import(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return archive_import_jobs.complete_upload(db, user, job_id)


@router.get("/{job_id}")
def archive_import_status(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return archive_import_jobs.get_archive_import_job_status(db, user, job_id)
