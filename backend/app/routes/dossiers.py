"""Authenticated private coaching dossier lifecycle routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.dossiers import (
    job_payload,
    dossier_detail,
    dossier_markdown,
    enqueue_dossier,
    get_dossier_artifact,
    get_dossier_job,
    list_dossiers,
    retry_dossier_job,
)
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])


class DossierRequest(BaseModel):
    """Bounded Journey selection used for one immutable dossier snapshot."""

    window: Literal["30d", "90d", "365d", "all"] = "90d"
    sport: str = Field(default="all", min_length=1, max_length=40)
    goal: str = Field(
        default="all",
        min_length=1,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


@router.get("")
def dossier_library(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return only the current athlete's jobs and immutable dossier versions."""
    return list_dossiers(db, user.id)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_dossier(
    body: DossierRequest,
    response: Response,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue or reuse one idempotent dossier generation snapshot."""
    job = enqueue_dossier(
        db,
        user.id,
        window=body.window,
        sport=body.sport,
        goal=body.goal,
    )
    response.headers["Location"] = f"/api/dossiers/jobs/{job.id}"
    return job_payload(job)


@router.get("/jobs/{job_id}")
def dossier_job(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one owner-scoped asynchronous job."""
    return job_payload(get_dossier_job(db, user.id, job_id))


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_dossier(
    job_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Safely retry one owned failed or insufficient job."""
    return job_payload(retry_dossier_job(db, user.id, job_id))


@router.get("/{artifact_id}")
def private_dossier(
    artifact_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one immutable owner-scoped dossier version."""
    return dossier_detail(db, user.id, artifact_id)


@router.get("/{artifact_id}/export", response_class=PlainTextResponse)
def export_private_dossier(
    artifact_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly export one owned dossier without enabling public sharing."""
    artifact = get_dossier_artifact(db, user.id, artifact_id)
    filename = f"fitness-pals-dossier-v{artifact.version}.md"
    return PlainTextResponse(
        dossier_markdown(artifact),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
