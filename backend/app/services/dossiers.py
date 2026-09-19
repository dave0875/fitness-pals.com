"""Private, deterministic coaching dossier lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, cast
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import DossierArtifact, DossierJob
from app.services.journey import build_journey


TERMINAL_JOB_STATES = {"completed", "insufficient_data", "failed"}
RETRYABLE_JOB_STATES = {"insufficient_data", "failed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _activity_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Allow-list canonical activity evidence stored with the request."""
    return {
        key: item.get(key)
        for key in (
            "id",
            "title",
            "sport",
            "start_time",
            "distance_m",
            "duration_seconds",
            "intensity",
            "goal",
        )
    }


def _bounded_snapshot(journey: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Journey response to safe, bounded evidence for immutable generation."""
    return {
        "filters": dict(journey.get("filters") or {}),
        "window": dict(journey.get("window") or {}),
        "freshness": dict(journey.get("freshness") or {}),
        "goal": journey.get("goal"),
        "totals": dict(journey.get("totals") or {}),
        "weekly_summaries": [
            dict(item) for item in (journey.get("weekly_summaries") or [])[:60]
        ],
        "monthly_summaries": [
            dict(item) for item in (journey.get("monthly_summaries") or [])[:24]
        ],
        "milestones": [
            dict(item) for item in (journey.get("milestones") or [])[:20]
        ],
        "activities": [
            _activity_snapshot(item)
            for item in (journey.get("activities") or [])[:100]
            if isinstance(item, dict)
        ],
    }


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dossier_eligibility(
    db: Session,
    user_id: uuid.UUID,
    *,
    window: str,
    sport: str,
    goal: str,
    journey_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check the selected canonical window each time the library opens."""
    builder = journey_builder or build_journey
    journey = builder(
        db=db,
        user_id=user_id,
        window=window,
        sport=sport,
        goal_filter=goal,
    )
    count = int((journey.get("totals") or {}).get("activity_count") or 0)
    return {
        "eligible": count > 0,
        "activity_count": count,
        "filters": {"window": window, "sport": sport, "goal": goal},
        "reason": (
            None
            if count
            else "No canonical activities match this selection. Choose another window or import activity history."
        ),
    }


def _distance_miles(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 1609.344, 1)
    except (TypeError, ValueError):
        return None


def _distance_text(value: Any) -> str:
    miles = _distance_miles(value)
    return f"{miles:.1f} miles" if miles is not None else "distance unknown"


def build_dossier_content(
    snapshot: dict[str, Any],
    *,
    version: int,
) -> dict[str, Any]:
    """Generate a deterministic coach-readable dossier from one frozen snapshot."""
    filters = snapshot.get("filters") or {}
    freshness = snapshot.get("freshness") or {}
    totals = snapshot.get("totals") or {}
    activities = snapshot.get("activities") or []
    gaps = list(freshness.get("missing") or [])
    freshness_state = freshness.get("state") or "unknown"
    goal = snapshot.get("goal")
    goal_key = filters.get("goal")
    if not isinstance(goal, dict) and isinstance(goal_key, str) and goal_key != "all":
        goal = {
            "key": goal_key,
            "label": {
                "marathon": "Marathon",
                "half": "Half marathon",
                "recovery": "Recovery",
                "consistency": "Consistency",
            }.get(goal_key, goal_key.replace("_", " ").title()),
        }
    goal_label = goal.get("label") if isinstance(goal, dict) else None
    distance_text = _distance_text(totals.get("distance_m"))
    activity_count = int(totals.get("activity_count") or 0)
    active_days = int(totals.get("active_days") or 0)

    evidence = [
        {
            "label": item.get("title") or item.get("sport") or "Activity",
            "occurred_at": item.get("start_time"),
            "summary": (
                f"{_distance_text(item.get('distance_m'))} · "
                f"{round(float(item.get('duration_seconds') or 0) / 60)} minutes"
            ),
            "activity_href": f"/activities/{item.get('id')}",
        }
        for item in activities[:10]
        if item.get("id")
    ]
    evidence_finding = (
        f"{activity_count} activities across {active_days} active days produced "
        f"{distance_text} in the selected window."
    )
    if activity_count >= 8:
        inference = (
            "The visible activity frequency suggests an established training rhythm. "
            "Preserve consistency before adding more load."
        )
    else:
        inference = (
            "The visible activity frequency suggests the current priority is a repeatable "
            "training rhythm rather than aggressive progression."
        )
    if gaps:
        uncertainty = (
            "Recovery conclusions are limited because these signals are missing: "
            + ", ".join(gaps)
            + "."
        )
    elif freshness_state == "stale":
        uncertainty = "The snapshot is stale; refresh connected data before changing training."
    else:
        uncertainty = (
            "This dossier interprets only the selected connection window and does not "
            "assume facts outside it."
        )

    return {
        "schema_version": 1,
        "version": version,
        "title": (
            f"{goal_label} coaching dossier" if goal_label else "Personal coaching dossier"
        ),
        "goal": goal,
        "connection_window": {
            "key": filters.get("window") or "90d",
            "sport": filters.get("sport") or "all",
            "goal": filters.get("goal") or "all",
            "start": (snapshot.get("window") or {}).get("start"),
            "end": (snapshot.get("window") or {}).get("end"),
        },
        "data_through": freshness.get("data_through"),
        "freshness": freshness_state,
        "material_gaps": gaps,
        "assumptions": [
            "Canonical activities are de-duplicated before dossier generation.",
            "Missing metrics remain unknown and are not treated as zero.",
            "The selected window is the complete evidence boundary for this version.",
        ],
        "summary": evidence_finding,
        "evidence": evidence,
        "findings": {
            "evidence": [evidence_finding],
            "inference": [inference],
            "uncertainty": [uncertainty],
        },
        "next_actions": [
            "Review the linked activities for context before changing the plan.",
            (
                "Refresh missing or stale recovery data."
                if gaps or freshness_state == "stale"
                else "Protect the next easy day while maintaining the visible rhythm."
            ),
        ],
        "journey_href": (
            f"/journey?window={filters.get('window', '90d')}"
            f"&sport={filters.get('sport', 'all')}"
            f"&goal={filters.get('goal', 'all')}"
        ),
        "privacy": {
            "visibility": "private",
            "export_available": True,
            "public_share_enabled": False,
        },
    }


def enqueue_dossier(
    db: Session,
    user_id: uuid.UUID,
    *,
    window: str,
    sport: str,
    goal: str,
    journey_builder: Callable[..., dict[str, Any]] | None = None,
) -> DossierJob:
    """Queue one idempotent generation request from a frozen athlete snapshot."""
    builder = journey_builder or build_journey
    if journey_builder is None:
        journey = builder(
            db,
            user_id,
            window=window,
            sport=sport,
            goal_filter=goal,
        )
    else:
        journey = builder(
            db=db,
            user_id=user_id,
            window=window,
            sport=sport,
            goal_filter=goal,
        )
    snapshot = _bounded_snapshot(journey)
    digest = _snapshot_hash(snapshot)
    existing = next(
        (
            item
            for item in db.query(DossierJob)
            .filter(
                DossierJob.user_id == user_id,
                DossierJob.snapshot_hash == digest,
            )
            .all()
            if getattr(item, "user_id", None) == user_id
            and getattr(item, "snapshot_hash", None) == digest
        ),
        None,
    )
    if existing is not None:
        return existing

    created_at = _now()
    job = DossierJob(
        id=uuid.uuid4(),
        user_id=user_id,
        status="queued",
        snapshot_hash=digest,
        request_json={
            "filters": {"window": window, "sport": sport, "goal": goal},
            "snapshot": snapshot,
        },
        error_json=None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


def _artifact_version(db: Session, user_id: uuid.UUID) -> int:
    versions = [
        int(item.version)
        for item in db.query(DossierArtifact)
        .filter(DossierArtifact.user_id == user_id)
        .all()
        if getattr(item, "user_id", None) == user_id
    ]
    return max(versions, default=0) + 1


def process_dossier_job(
    db: Session,
    job: DossierJob,
) -> DossierArtifact | None:
    """Generate one immutable artifact from the job's frozen safe snapshot."""
    request = job.request_json if isinstance(job.request_json, dict) else {}
    snapshot = request.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("Dossier job is missing its bounded snapshot")

    started = _now()
    job.status = "generating"
    job.started_at = started
    job.updated_at = started
    db.commit()

    activity_count = int((snapshot.get("totals") or {}).get("activity_count") or 0)
    if activity_count <= 0:
        finished = _now()
        job.status = "insufficient_data"
        job.error_json = {
            "category": "insufficient_data",
            "message": "No canonical activities are available in this snapshot.",
        }
        job.finished_at = finished
        job.updated_at = finished
        db.commit()
        return None

    existing = next(
        (
            item
            for item in db.query(DossierArtifact)
            .filter(DossierArtifact.job_id == job.id)
            .all()
            if getattr(item, "job_id", None) == job.id
        ),
        None,
    )
    if existing is not None:
        job.status = "completed"
        db.commit()
        return existing

    version = _artifact_version(db, cast(uuid.UUID, job.user_id))
    content = build_dossier_content(snapshot, version=version)
    finished = _now()
    artifact = DossierArtifact(
        id=uuid.uuid4(),
        user_id=job.user_id,
        job_id=job.id,
        version=version,
        snapshot_hash=job.snapshot_hash,
        content_json=content,
        data_through=_parse_datetime(content.get("data_through")),
        created_at=finished,
        updated_at=finished,
    )
    db.add(artifact)
    job.status = "completed"
    job.error_json = None
    job.finished_at = finished
    job.updated_at = finished
    db.commit()
    return artifact


def process_pending_dossier_jobs(
    db: Session,
    *,
    limit: int = 5,
) -> dict[str, int]:
    """Process queued dossier jobs and reduce failures to safe categories."""
    jobs = (
        db.query(DossierJob)
        .filter(DossierJob.status == "queued")
        .order_by(DossierJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    processed = completed = failed = insufficient = 0
    for job in jobs:
        if getattr(job, "status", None) != "queued":
            continue
        processed += 1
        try:
            artifact = process_dossier_job(db, job)
            if artifact is None:
                insufficient += 1
            else:
                completed += 1
        except Exception as exc:  # pylint: disable=broad-except
            db.rollback()
            finished = _now()
            job.status = "failed"
            job.error_json = {
                "category": "generation",
                "message": type(exc).__name__,
            }
            job.finished_at = finished
            job.updated_at = finished
            db.commit()
            failed += 1
    return {
        "processed": processed,
        "completed": completed,
        "insufficient": insufficient,
        "failed": failed,
    }


def job_payload(job: DossierJob) -> dict[str, Any]:
    request = job.request_json if isinstance(job.request_json, dict) else {}
    return {
        "id": str(job.id),
        "status": job.status,
        "filters": request.get("filters") or {},
        "activity_count": int(
            ((request.get("snapshot") or {}).get("totals") or {}).get(
                "activity_count"
            )
            or 0
        ),
        "retryable": job.status in RETRYABLE_JOB_STATES,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_category": (
            job.error_json.get("category")
            if isinstance(job.error_json, dict)
            else None
        ),
    }


def _artifact_payload(
    artifact: DossierArtifact,
    *,
    state: str,
) -> dict[str, Any]:
    content = artifact.content_json if isinstance(artifact.content_json, dict) else {}
    return {
        "id": str(artifact.id),
        "job_id": str(artifact.job_id),
        "version": artifact.version,
        "state": state,
        "title": content.get("title") or f"Coaching dossier v{artifact.version}",
        "summary": content.get("summary"),
        "data_through": (
            artifact.data_through.isoformat() if artifact.data_through else None
        ),
        "freshness": content.get("freshness"),
        "goal": content.get("goal"),
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


def list_dossiers(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """List current athlete jobs and immutable artifact versions."""
    jobs = [
        item
        for item in db.query(DossierJob)
        .filter(DossierJob.user_id == user_id)
        .all()
        if getattr(item, "user_id", None) == user_id
    ]
    artifacts = [
        item
        for item in db.query(DossierArtifact)
        .filter(DossierArtifact.user_id == user_id)
        .all()
        if getattr(item, "user_id", None) == user_id
    ]
    jobs.sort(
        key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    artifacts.sort(key=lambda item: int(item.version), reverse=True)
    artifact_payloads = [
        _artifact_payload(
            artifact,
            state="completed" if index == 0 else "superseded",
        )
        for index, artifact in enumerate(artifacts)
    ]
    return {
        "latest": artifact_payloads[0] if artifact_payloads else None,
        "artifacts": artifact_payloads,
        "jobs": [job_payload(job) for job in jobs if job.status != "completed"],
        "privacy": {
            "visibility": "private",
            "public_samples_are_personal": False,
        },
    }


def get_dossier_job(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> DossierJob:
    job = next(
        (
            item
            for item in db.query(DossierJob)
            .filter(DossierJob.id == job_id, DossierJob.user_id == user_id)
            .all()
            if getattr(item, "id", None) == job_id
            and getattr(item, "user_id", None) == user_id
        ),
        None,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Dossier job not found")
    return job


def retry_dossier_job(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> DossierJob:
    """Safely return an owned failed or insufficient job to the queue."""
    job = get_dossier_job(db, user_id, job_id)
    if job.status not in RETRYABLE_JOB_STATES:
        raise HTTPException(status_code=409, detail="Dossier job is not retryable")
    job.status = "queued"
    job.error_json = None
    job.started_at = None
    job.finished_at = None
    job.updated_at = _now()
    db.commit()
    return job


def get_dossier_artifact(
    db: Session,
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> DossierArtifact:
    artifact = next(
        (
            item
            for item in db.query(DossierArtifact)
            .filter(
                DossierArtifact.id == artifact_id,
                DossierArtifact.user_id == user_id,
            )
            .all()
            if getattr(item, "id", None) == artifact_id
            and getattr(item, "user_id", None) == user_id
        ),
        None,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return artifact


def dossier_detail(
    db: Session,
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> dict[str, Any]:
    artifact = get_dossier_artifact(db, user_id, artifact_id)
    return {
        "id": str(artifact.id),
        "job_id": str(artifact.job_id),
        "version": artifact.version,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "content": artifact.content_json,
    }


def dossier_markdown(artifact: DossierArtifact) -> str:
    """Render an owner-authorized artifact as an explicit private export."""
    content = artifact.content_json if isinstance(artifact.content_json, dict) else {}
    findings = content.get("findings") or {}
    lines = [
        f"# {content.get('title', 'Personal coaching dossier')}",
        "",
        f"Version: {artifact.version}",
        f"Data through: {content.get('data_through') or 'Unknown'}",
        f"Freshness: {content.get('freshness') or 'Unknown'}",
        "",
        "## Summary",
        str(content.get("summary") or "No summary available."),
        "",
        "## Evidence",
        *[f"- {item}" for item in findings.get("evidence") or []],
        "",
        "## Inference",
        *[f"- {item}" for item in findings.get("inference") or []],
        "",
        "## Uncertainty",
        *[f"- {item}" for item in findings.get("uncertainty") or []],
        "",
        "## Next actions",
        *[f"- {item}" for item in content.get("next_actions") or []],
        "",
        "Private export — not a medical diagnosis.",
    ]
    return "\n".join(lines)
