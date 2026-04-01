"""Application service for provider sync job orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import SyncCheckpoint, SyncJob
from app.services.garmin import activity as garmin_activity
from app.services import garmin_ingest
from app.types import CurrentUserLike


@dataclass
class SyncExecutionResult:
    """Return shape for an executed provider sync."""

    job: SyncJob
    ingest_run: Any


def enqueue_sync_job(
    db: Session,
    *,
    user_id: UUID,
    provider: str,
    trigger: str = "manual",
    test_run: bool = False,
    payload: Optional[dict[str, Any]] = None,
) -> SyncJob:
    """Persist a queued sync job."""
    job = SyncJob(
        user_id=user_id,
        provider=provider,
        status="queued",
        trigger=trigger,
        test_run=test_run,
        payload_json=payload,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def mark_sync_job_running(db: Session, job: SyncJob) -> SyncJob:
    """Mark a sync job as running."""
    job.status = "running"  # type: ignore[assignment]
    job.started_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    job.error_json = None  # type: ignore[assignment]
    db.commit()
    db.refresh(job)
    return job


def mark_sync_job_completed(
    db: Session,
    job: SyncJob,
    *,
    result: Optional[dict[str, Any]] = None,
    ingest_run_id: Optional[UUID] = None,
) -> SyncJob:
    """Mark a sync job as completed."""
    job.status = "completed"  # type: ignore[assignment]
    job.result_json = result  # type: ignore[assignment]
    job.error_json = None  # type: ignore[assignment]
    job.ingest_run_id = ingest_run_id  # type: ignore[assignment]
    job.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()
    db.refresh(job)
    return job


def mark_sync_job_failed(
    db: Session,
    job: SyncJob,
    *,
    error: dict[str, Any],
) -> SyncJob:
    """Mark a sync job as failed."""
    job.status = "failed"  # type: ignore[assignment]
    job.error_json = error  # type: ignore[assignment]
    job.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()
    db.refresh(job)
    return job


def get_sync_checkpoint(
    db: Session,
    *,
    user_id: UUID,
    provider: str,
) -> Optional[SyncCheckpoint]:
    """Return an existing sync checkpoint if present."""
    return (
        db.query(SyncCheckpoint)
        .filter(
            SyncCheckpoint.user_id == user_id,
            SyncCheckpoint.provider == provider,
        )
        .first()
    )


def upsert_sync_checkpoint(
    db: Session,
    *,
    user_id: UUID,
    provider: str,
    status: str,
    cursor: Optional[dict[str, Any]] = None,
    error: Optional[dict[str, Any]] = None,
    last_synced_at: Optional[datetime] = None,
    last_sync_job_id: Optional[UUID] = None,
    last_ingest_run_id: Optional[UUID] = None,
) -> SyncCheckpoint:
    """Create or update the durable sync cursor for a provider connection."""
    checkpoint = get_sync_checkpoint(db, user_id=user_id, provider=provider)
    if checkpoint is None:
        checkpoint = SyncCheckpoint(
            user_id=user_id,
            provider=provider,
            status=status,
            cursor_json=cursor,
            error_json=error,
            last_synced_at=last_synced_at,
            last_sync_job_id=last_sync_job_id,
            last_ingest_run_id=last_ingest_run_id,
        )
        db.add(checkpoint)
    else:
        checkpoint.status = status  # type: ignore[assignment]
        checkpoint.cursor_json = cursor  # type: ignore[assignment]
        checkpoint.error_json = error  # type: ignore[assignment]
        checkpoint.last_synced_at = last_synced_at  # type: ignore[assignment]
        checkpoint.last_sync_job_id = last_sync_job_id  # type: ignore[assignment]
        checkpoint.last_ingest_run_id = last_ingest_run_id  # type: ignore[assignment]
    db.commit()
    db.refresh(checkpoint)
    return checkpoint


def _sync_error_payload(exc: Exception) -> dict[str, Any]:
    """Normalize a sync exception into structured metadata."""
    detail = getattr(exc, "detail", None)
    status_code = getattr(exc, "status_code", None)
    message = detail if detail is not None else str(exc)
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(message),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def _checkpoint_cursor_for_garmin(db: Session, user: CurrentUserLike) -> dict[str, Any]:
    """Capture the current Garmin sync boundary from canonical storage."""
    latest_start_time = garmin_activity.get_latest_activity_start_time(db, user)
    return {
        "latest_activity_start_time": (
            latest_start_time.isoformat() if latest_start_time else None
        ),
    }


def run_garmin_sync_job(
    db: Session,
    *,
    user: CurrentUserLike,
    trigger: str = "manual",
    test_run: bool = False,
) -> SyncExecutionResult:
    """Queue and execute a Garmin sync job for a single user."""
    job = enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger=trigger,
        test_run=test_run,
    )
    mark_sync_job_running(db, job)
    try:
        ingest_run = garmin_ingest.fetch_garmin_recent(db, user, test_run=test_run)
        completed_at = getattr(ingest_run, "finished_at", None) or datetime.now(timezone.utc)
        upsert_sync_checkpoint(
            db,
            user_id=user.id,
            provider="garmin",
            status="ok",
            cursor=_checkpoint_cursor_for_garmin(db, user),
            error=None,
            last_synced_at=completed_at,
            last_sync_job_id=job.id,
            last_ingest_run_id=getattr(ingest_run, "id", None),
        )
        mark_sync_job_completed(
            db,
            job,
            result={
                "ingest_run_id": str(getattr(ingest_run, "id", "")),
                "summary": getattr(ingest_run, "summary", None),
            },
            ingest_run_id=getattr(ingest_run, "id", None),
        )
        return SyncExecutionResult(job=job, ingest_run=ingest_run)
    except Exception as exc:
        upsert_sync_checkpoint(
            db,
            user_id=user.id,
            provider="garmin",
            status="error",
            cursor=None,
            error=_sync_error_payload(exc),
            last_synced_at=None,
            last_sync_job_id=job.id,
            last_ingest_run_id=None,
        )
        mark_sync_job_failed(db, job, error=_sync_error_payload(exc))
        raise
