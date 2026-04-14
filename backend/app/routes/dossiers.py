"""Public dossier listing and authenticated dossier import endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import PublishedDossier
from app.services.garmin_export_import import import_garmin_export_archive
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])


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
