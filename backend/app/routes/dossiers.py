"""Public dossier listing and authenticated dossier import endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import PublishedDossier
from app.services import archive_import_jobs
from app.services.garmin_export_import import import_garmin_export_archive
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])


class GarminArchiveImportStartRequest(BaseModel):
    """Request payload for starting a staged archive upload."""

    filename: str
    content_type: str = "application/zip"
    size_bytes: int


@router.get("/public")
def list_public_dossiers(db: Session = Depends(get_db)):
    """Return all public non-sample dossiers published through the app."""
    dossiers = (
        db.query(PublishedDossier)
        .filter(PublishedDossier.public.is_(True))
        .order_by(PublishedDossier.created_at.desc())
        .all()
    )
    return [
        {
            "slug": dossier.slug,
            "title": dossier.title,
            "summary": dossier.summary,
            "athlete_name": dossier.athlete_name,
            "source": dossier.source,
        }
        for dossier in dossiers
    ]


@router.get("/public/{slug}")
def get_public_dossier(slug: str, db: Session = Depends(get_db)):
    """Return a single public dossier by slug."""
    dossier = (
        db.query(PublishedDossier)
        .filter(PublishedDossier.slug == slug, PublishedDossier.public.is_(True))
        .first()
    )
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return {
        "slug": dossier.slug,
        "title": dossier.title,
        "summary": dossier.summary,
        "athlete_name": dossier.athlete_name,
        "html": dossier.html_content,
    }


@router.post("/import/garmin-export")
async def import_garmin_export(
    archive: UploadFile = File(...),
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a Garmin export zip for the current user and publish a dossier."""
    filename = archive.filename or "Garmin Export.zip"
    archive_bytes = await archive.read()
    return import_garmin_export_archive(
        db=db,
        user=user,
        filename=filename,
        archive_bytes=archive_bytes,
    )


@router.post("/import/garmin-export/start")
def start_garmin_export_import(
    payload: GarminArchiveImportStartRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a staged archive import job and return its upload target."""
    return archive_import_jobs.create_archive_import_job(
        db,
        user,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )


@router.put("/import/uploads/{job_id}")
async def upload_garmin_export_archive(
    job_id: UUID,
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    """Receive app-mediated upload bytes for local filesystem staging."""
    return archive_import_jobs.receive_archive_import_upload(
        db,
        job_id=job_id,
        token=token,
        content=await request.body(),
    )


@router.post("/import/garmin-export/{job_id}/complete")
def complete_garmin_export_import(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an uploaded Garmin archive ready for async worker ingestion."""
    return archive_import_jobs.complete_archive_import_job(db, user, job_id)


@router.get("/import/garmin-export/{job_id}")
def get_garmin_export_import_status(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return current status for an archive import job."""
    return archive_import_jobs.get_archive_import_job_status(db, user, job_id)
