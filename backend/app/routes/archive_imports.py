"""Authenticated routes for asynchronous Garmin archive imports."""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services import archive_import_jobs
from app.services.archive_capabilities import archive_capabilities
from app.services.google_drive_archive import (
    configured_folder_for_user,
    exchange_google_drive_code,
    fetch_google_profile,
    get_user_google_drive_grant,
    google_drive_authorization_url,
    google_drive_oauth_configured,
    save_google_drive_grant,
)
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/archive-imports", tags=["archive-imports"])
DRIVE_OAUTH_SESSION_KEY = "google_drive_oauth"


class UploadStartRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/zip", max_length=255)
    size_bytes: int = Field(gt=0)


def _safe_next_path(candidate: str | None) -> str:
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return "/import/garmin-archive?drive=connected"
    return candidate


def _legacy_folder(user: CurrentUserLike) -> str | None:
    try:
        return configured_folder_for_user(user)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def _google_drive_status(db: Session, user: CurrentUserLike) -> dict:
    token = get_user_google_drive_grant(db, user)
    legacy_folder = _legacy_folder(user)
    oauth_available = google_drive_oauth_configured(db)
    return {
        "authorization_available": oauth_available,
        "connected": bool(token and oauth_available),
        "account_email": (token.metadata_json or {}).get("email") if token else None,
        "legacy_source_available": legacy_folder is not None,
        "can_import": bool((token and oauth_available) or legacy_folder),
        "authorization_url": (
            "/api/archive-imports/google-drive/authorize" if oauth_available else None
        ),
    }


@router.get("/capabilities")
def capabilities(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disclose only whether this athlete can use each archive path."""
    legacy = archive_capabilities(user)
    drive = _google_drive_status(db, user)
    if drive["can_import"]:
        reason = None
    elif drive["authorization_available"]:
        reason = "Authorize Google Drive to search for Garmin data."
    else:
        reason = "Google Drive authorization has not been configured for this deployment."
    return {
        **legacy,
        "drive": {**drive, "available": drive["can_import"], "reason": reason},
        "latest_job": archive_import_jobs.latest_archive_import_job_status(db, user),
    }


@router.get("/google-drive/status")
def google_drive_status(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Describe whether this athlete can authorize or import from Drive."""
    return _google_drive_status(db, user)


@router.get("/google-drive/authorize")
def authorize_google_drive(
    request: Request,
    next_path: str | None = None,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a separate read-only Drive grant for the signed-in Google address."""
    state = secrets.token_urlsafe(32)
    request.session[DRIVE_OAUTH_SESSION_KEY] = {
        "state": state,
        "user_id": str(user.id),
        "next": _safe_next_path(next_path),
    }
    return RedirectResponse(
        google_drive_authorization_url(
            db,
            state=state,
            login_hint=str(getattr(user, "email", "")),
        ),
        status_code=302,
    )


@router.get("/google-drive/callback")
def google_drive_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate Google's callback and persist the athlete-owned encrypted grant."""
    pending = request.session.pop(DRIVE_OAUTH_SESSION_KEY, None)
    if (
        not isinstance(pending, dict)
        or not state
        or not secrets.compare_digest(state, str(pending.get("state") or ""))
        or str(pending.get("user_id") or "") != str(user.id)
    ):
        raise HTTPException(status_code=400, detail="Invalid Google Drive authorization state")
    if error:
        raise HTTPException(status_code=400, detail="Google Drive authorization was cancelled")
    if not code:
        raise HTTPException(status_code=400, detail="Google did not return an authorization code")
    token_payload = exchange_google_drive_code(db, code)
    profile = fetch_google_profile(str(token_payload["access_token"]))
    save_google_drive_grant(db, user, token_payload, profile)
    return RedirectResponse(_safe_next_path(pending.get("next")), status_code=303)

@router.post("/google-drive", status_code=status.HTTP_202_ACCEPTED)
def start_google_drive_import(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue the athlete's authorized Drive, with legacy folder assignment fallback."""
    token = get_user_google_drive_grant(db, user)
    if token is not None and google_drive_oauth_configured(db):
        job = archive_import_jobs.create_drive_import_job(
            db,
            user,
            folder_id="root",
            authorization="user_oauth",
        )
    else:
        if not archive_capabilities(user)["drive"]["available"]:
            raise HTTPException(
                status_code=503,
                detail="Google Drive archive is unavailable for this account",
            )
        folder_id = configured_folder_for_user(user)
        job = archive_import_jobs.create_drive_import_job(db, user, folder_id=folder_id)
    return archive_import_jobs.get_archive_import_job_status(db, user, UUID(str(job.id)))


@router.post("/uploads/start")
def start_upload_import(
    payload: UploadStartRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not archive_capabilities(user)["upload"]["available"]:
        raise HTTPException(status_code=503, detail="Archive upload is unavailable")
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
