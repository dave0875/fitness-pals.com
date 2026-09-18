"""Tests for the private coaching dossier lifecycle."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from fastapi import HTTPException
import pytest

from app.models import DossierArtifact, DossierJob
from app.services.dossiers import (
    build_dossier_content,
    enqueue_dossier,
    get_dossier_artifact,
    list_dossiers,
    process_dossier_job,
    retry_dossier_job,
)


class FakeQuery:
    """Small query facade used by dossier unit tests."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *criteria):
        return self

    def order_by(self, *criteria):
        return self

    def with_for_update(self, **kwargs):
        return self

    def limit(self, value):
        return FakeQuery(self.items[:value])

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None


class FakeSession:
    """In-memory model store with the subset of Session used by the service."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.commits = 0

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def add(self, item):
        if item not in self.items:
            self.items.append(item)

    def commit(self):
        self.commits += 1

    def flush(self):
        return None

    def rollback(self):
        return None


def journey_snapshot(activity_count=2, freshness="fresh"):
    """Return one bounded canonical Journey response."""
    return {
        "filters": {"window": "90d", "sport": "run", "goal": "marathon"},
        "window": {
            "start": "2026-05-05T12:00:00+00:00",
            "end": "2026-08-03T12:00:00+00:00",
        },
        "freshness": {
            "state": freshness,
            "data_through": "2026-08-02T12:00:00+00:00",
            "missing": ["sleep"] if freshness == "partial" else [],
        },
        "goal": {"key": "marathon", "label": "Marathon"},
        "totals": {
            "activity_count": activity_count,
            "distance_m": 42195.0 if activity_count else 0.0,
            "duration_seconds": 14400 if activity_count else 0,
            "active_days": activity_count,
            "intensity_distribution": {"easy": 1, "moderate": 1, "hard": 0}
            if activity_count
            else None,
        },
        "weekly_summaries": [
            {
                "period_start": "2026-07-27",
                "activity_count": activity_count,
                "distance_m": 42195.0 if activity_count else 0.0,
                "duration_seconds": 14400 if activity_count else 0,
                "active_days": activity_count,
                "average_sleep_hours": None,
            }
        ],
        "monthly_summaries": [],
        "milestones": [
            {
                "kind": "longest_activity",
                "label": "Longest activity in this window",
                "activity_id": "11111111-1111-1111-1111-111111111111",
                "distance_m": 30000.0,
            }
        ]
        if activity_count
        else [],
        "activities": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "title": "Long run",
                "sport": "run",
                "start_time": "2026-08-02T12:00:00+00:00",
                "distance_m": 30000.0,
                "duration_seconds": 10800,
                "intensity": "easy",
                "status": "merged",
                "goal": "marathon",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "title": "Tempo run",
                "sport": "run",
                "start_time": "2026-07-30T12:00:00+00:00",
                "distance_m": 12195.0,
                "duration_seconds": 3600,
                "intensity": "moderate",
                "status": "merged",
                "goal": "marathon",
            },
        ][:activity_count],
    }


def test_dossier_never_turns_unknown_distance_into_zero_miles():
    snapshot = journey_snapshot()
    snapshot["totals"]["distance_m"] = None
    snapshot["activities"][0]["distance_m"] = None
    content = build_dossier_content(snapshot, version=1)
    assert "distance unknown" in content["summary"]
    assert "distance unknown" in content["evidence"][0]["summary"]
    assert "0.0 miles" not in content["summary"]


def test_dossier_content_is_deterministic_and_explains_reasoning_boundaries():
    """Generation produces stable coach-readable evidence and uncertainty sections."""
    snapshot = journey_snapshot(freshness="partial")

    first = build_dossier_content(snapshot, version=1)
    second = build_dossier_content(deepcopy(snapshot), version=1)

    assert first == second
    assert first["data_through"] == "2026-08-02T12:00:00+00:00"
    assert first["connection_window"]["key"] == "90d"
    assert first["material_gaps"] == ["sleep"]
    assert first["evidence"][0]["activity_href"].startswith("/activities/")
    assert first["findings"]["evidence"]
    assert first["findings"]["inference"]
    assert first["findings"]["uncertainty"]
    assert first["next_actions"]
    assert first["privacy"]["visibility"] == "private"


def test_enqueue_is_idempotent_per_athlete_snapshot_and_isolates_other_users():
    """The same athlete snapshot reuses its queued job without crossing users."""
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db = FakeSession()

    first = enqueue_dossier(
        db,
        athlete_id,
        window="90d",
        sport="run",
        goal="marathon",
        journey_builder=lambda **kwargs: journey_snapshot(),
    )
    repeated = enqueue_dossier(
        db,
        athlete_id,
        window="90d",
        sport="run",
        goal="marathon",
        journey_builder=lambda **kwargs: journey_snapshot(),
    )
    other = enqueue_dossier(
        db,
        other_id,
        window="90d",
        sport="run",
        goal="marathon",
        journey_builder=lambda **kwargs: journey_snapshot(),
    )

    assert first.id == repeated.id
    assert first.snapshot_hash == repeated.snapshot_hash
    assert other.id != first.id
    assert other.user_id == other_id
    assert len([item for item in db.items if isinstance(item, DossierJob)]) == 2


def test_worker_generates_immutable_version_and_library_marks_history_superseded():
    """Completed artifacts remain immutable while newer versions become latest."""
    athlete_id = uuid.uuid4()
    db = FakeSession()
    first_job = enqueue_dossier(
        db,
        athlete_id,
        window="90d",
        sport="run",
        goal="marathon",
        journey_builder=lambda **kwargs: journey_snapshot(),
    )
    first_artifact = process_dossier_job(db, first_job)
    original_content = deepcopy(first_artifact.content_json)

    changed = journey_snapshot()
    changed["freshness"]["data_through"] = "2026-08-03T12:00:00+00:00"
    changed["activities"][0]["distance_m"] = 32000.0
    second_job = enqueue_dossier(
        db,
        athlete_id,
        window="90d",
        sport="run",
        goal="marathon",
        journey_builder=lambda **kwargs: changed,
    )
    second_artifact = process_dossier_job(db, second_job)
    library = list_dossiers(db, athlete_id)

    assert first_artifact.content_json == original_content
    assert first_artifact.version == 1
    assert second_artifact.version == 2
    assert library["artifacts"][0]["state"] == "completed"
    assert library["artifacts"][1]["state"] == "superseded"
    assert library["latest"]["id"] == str(second_artifact.id)


def test_insufficient_data_and_failed_jobs_are_safely_retryable():
    """Empty snapshots become recoverable without manufacturing recommendations."""
    athlete_id = uuid.uuid4()
    db = FakeSession()
    job = enqueue_dossier(
        db,
        athlete_id,
        window="30d",
        sport="all",
        goal="all",
        journey_builder=lambda **kwargs: journey_snapshot(activity_count=0, freshness="empty"),
    )

    assert process_dossier_job(db, job) is None
    assert job.status == "insufficient_data"
    retried = retry_dossier_job(db, athlete_id, job.id)
    assert retried.status == "queued"
    assert retried.error_json is None


def test_dossier_detail_and_retry_reject_cross_athlete_access():
    """Artifacts and jobs owned by another athlete are indistinguishable from missing."""
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    job = DossierJob(
        id=uuid.uuid4(),
        user_id=owner_id,
        status="failed",
        snapshot_hash="private",
        request_json={"snapshot": journey_snapshot()},
        error_json={"category": "generation"},
    )
    artifact = DossierArtifact(
        id=uuid.uuid4(),
        user_id=owner_id,
        job_id=job.id,
        version=1,
        snapshot_hash="private",
        content_json=build_dossier_content(journey_snapshot(), version=1),
        data_through=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
    )
    db = FakeSession([job, artifact])

    with pytest.raises(HTTPException) as detail_error:
        get_dossier_artifact(db, other_id, artifact.id)
    with pytest.raises(HTTPException) as retry_error:
        retry_dossier_job(db, other_id, job.id)

    assert detail_error.value.status_code == 404
    assert retry_error.value.status_code == 404
