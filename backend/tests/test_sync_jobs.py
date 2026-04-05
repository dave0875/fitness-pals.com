"""Tests for sync job orchestration helpers."""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

from app.models import SyncCheckpoint, SyncJob
from app.services import sync_jobs


class FakeSession:
    """Minimal SQLAlchemy-like session stub for sync job tests."""

    def __init__(self):
        self.items = []
        self.added = []

    def add(self, obj):
        self.items.append(obj)
        self.added.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        return obj

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for tests."""

    def __init__(self, data):
        self.data = data

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def first(self):
        return self.data[0] if self.data else None

    @staticmethod
    def _resolve_value(side, item):
        if isinstance(side, BindParameter):
            return side.value
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        return side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            if condition.operator is operators.and_:
                return all(self._matches(c, item) for c in condition.clauses)
            if condition.operator is operators.or_:
                return any(self._matches(c, item) for c in condition.clauses)
        if isinstance(condition, BinaryExpression):
            left = self._resolve_value(condition.left, item)
            right = self._resolve_value(condition.right, item)
            return condition.operator(left, right)
        return True


def test_enqueue_and_complete_sync_job_records_result():
    """Sync jobs should move through queued, running, and completed states."""
    db = FakeSession()
    user_id = uuid.uuid4()

    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user_id,
        provider="garmin",
        trigger="manual",
        test_run=True,
        payload={"window": "recent"},
    )
    assert job.status == "queued"
    assert job.test_run is True

    running = sync_jobs.mark_sync_job_running(db, job)
    assert running.status == "running"
    assert running.started_at is not None

    ingest_run_id = uuid.uuid4()
    completed = sync_jobs.mark_sync_job_completed(
        db,
        job,
        result={"ingest_run_id": str(ingest_run_id)},
        ingest_run_id=ingest_run_id,
    )
    assert completed.status == "completed"
    assert completed.finished_at is not None
    assert completed.result_json["ingest_run_id"] == str(ingest_run_id)
    assert completed.ingest_run_id == ingest_run_id


def test_upsert_sync_checkpoint_updates_existing_cursor():
    """Checkpoint upsert should update the existing provider boundary."""
    db = FakeSession()
    user_id = uuid.uuid4()

    first = sync_jobs.upsert_sync_checkpoint(
        db,
        user_id=user_id,
        provider="garmin",
        status="ok",
        cursor={"latest_activity_start_time": "2026-03-01T00:00:00+00:00"},
    )
    assert first.status == "ok"

    second = sync_jobs.upsert_sync_checkpoint(
        db,
        user_id=user_id,
        provider="garmin",
        status="error",
        cursor={"latest_activity_start_time": "2026-03-02T00:00:00+00:00"},
        error={"message": "boom"},
    )
    assert first.id == second.id
    assert second.status == "error"
    assert second.cursor_json["latest_activity_start_time"] == "2026-03-02T00:00:00+00:00"
    assert second.error_json["message"] == "boom"


def test_run_garmin_sync_job_queues_job_without_inline_ingest(monkeypatch):
    """Queue helpers should persist the job without executing ingest inline."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    monkeypatch.setattr(
        sync_jobs.garmin_ingest,
        "fetch_garmin_recent",
        lambda *_args, **_kwargs: pytest.fail("queueing should not execute ingest inline"),
    )

    result = sync_jobs.run_garmin_sync_job(db, user=user)

    assert result.job.status == "queued"
    assert result.ingest_run is None
    assert result.job.provider == "garmin"
    assert result.job.trigger == "manual"
    assert result.job.user_id == user.id
    assert result.job.test_run is False


def test_process_sync_job_records_checkpoint_and_result(monkeypatch):
    """Worker processing should update job status and checkpoint cursor."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    ingest_run_id = uuid.uuid4()
    finished_at = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.timezone.utc)
    latest_activity = datetime.datetime(2026, 4, 1, 11, 30, tzinfo=datetime.timezone.utc)

    def fake_fetch(db_arg, user_arg, test_run=False):  # pylint: disable=unused-argument
        assert user_arg.id == user.id
        assert test_run is False
        return SimpleNamespace(id=ingest_run_id, summary={"activities": 2}, finished_at=finished_at)

    monkeypatch.setattr(sync_jobs.garmin_ingest, "fetch_garmin_recent", fake_fetch)
    monkeypatch.setattr(
        sync_jobs.garmin_activity,
        "get_latest_activity_start_time",
        lambda db_arg, user_arg: latest_activity,
    )
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="manual",
    )

    result = sync_jobs.process_sync_job(db, job)

    assert result.job.status == "completed"
    assert result.job.result_json["ingest_run_id"] == str(ingest_run_id)
    checkpoint = sync_jobs.get_sync_checkpoint(db, user_id=user.id, provider="garmin")
    assert checkpoint is not None
    assert checkpoint.status == "ok"
    assert checkpoint.last_ingest_run_id == ingest_run_id
    assert checkpoint.cursor_json["latest_activity_start_time"] == latest_activity.isoformat()


def test_process_sync_job_marks_failure(monkeypatch):
    """Worker failures should be recorded on both the sync job and checkpoint."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)

    def fake_fetch(db_arg, user_arg, test_run=False):  # pylint: disable=unused-argument
        raise HTTPException(status_code=502, detail="Garmin fetch failed")

    monkeypatch.setattr(sync_jobs.garmin_ingest, "fetch_garmin_recent", fake_fetch)
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="manual",
    )

    with pytest.raises(HTTPException):
        sync_jobs.process_sync_job(db, job)

    jobs = [item for item in db.items if isinstance(item, SyncJob)]
    checkpoints = [item for item in db.items if isinstance(item, SyncCheckpoint)]
    assert jobs and jobs[0].status == "failed"
    assert jobs[0].error_json["message"] == "Garmin fetch failed"
    assert checkpoints and checkpoints[0].status == "error"
    assert checkpoints[0].error_json["status_code"] == 502


def test_process_pending_sync_jobs_marks_unsupported_provider_failed_once():
    """Worker draining should fail unsupported jobs once instead of requeueing them forever."""
    db = FakeSession()
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=uuid.uuid4(),
        provider="polar",
        trigger="manual",
    )

    summary = sync_jobs.process_pending_sync_jobs(db, limit=2)

    assert summary == {"processed": 1, "failed": 1}
    assert job.status == "failed"
    assert job.error_json["message"] == "Unsupported sync provider: polar"
