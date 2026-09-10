"""Slice 5 red tests for sync worker/runtime separation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter


os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s=")
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_ID", "test-google-client")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_SECRET", "test-google-secret")
os.environ.setdefault("RUNTRAINER_GOOGLE_REDIRECT_URI", "https://example.com/auth/google/callback")
os.environ.setdefault("GARMIN_MODE", "oauth")

from app.models import SyncCheckpoint, SyncJob, UserProviderToken
from app.routes import providers_garmin
from app.services import garmin_scheduler, sync_jobs


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for these tests."""

    def __init__(self, data):
        self.data = list(data)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def all(self):
        return list(self.data)

    def first(self):
        return self.data[0] if self.data else None

    def count(self):
        return len(self.data)

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


class FakeSession:
    """Minimal SQLAlchemy-like session stub for worker/runtime tests."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        return obj

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


def _fake_user(tenant_id=None):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id)


def _fake_influx_client():
    class FakeWriteAPI:
        def write(self, **_kwargs):
            return None

    class FakeQueryAPI:
        def query(self, **_kwargs):
            return []

    class FakeDeleteAPI:
        def delete(self, **_kwargs):
            return None

    return SimpleNamespace(
        org="org",
        default_bucket="bucket",
        write_api=lambda: FakeWriteAPI(),
        query_api=lambda: FakeQueryAPI(),
        delete_api=lambda: FakeDeleteAPI(),
    )


def test_api_enqueue_path_returns_queued_job_without_inline_ingest(monkeypatch):
    """The Garmin API should enqueue work and not report an inline ingest result."""
    monkeypatch.setattr(
        sync_jobs.garmin_ingest,
        "fetch_garmin_recent",
        lambda *_args, **_kwargs: pytest.fail("garmin_fetch still executes inline ingest"),
    )
    fake_job_id = uuid.uuid4()
    fake_execution = SimpleNamespace(
        job=SimpleNamespace(id=fake_job_id, status="queued"),
        ingest_run=SimpleNamespace(id=uuid.uuid4(), summary={}),
    )
    monkeypatch.setattr(providers_garmin, "run_garmin_sync_job", lambda *_args, **_kwargs: fake_execution)

    db = FakeSession()
    user = _fake_user()
    response = providers_garmin.garmin_fetch(user=user, db=db)

    assert response["status"] == "queued"
    assert response["sync_job_id"] == str(fake_job_id)
    assert response["ingested"] == 0


def test_worker_processes_pending_job_and_updates_checkpoint(monkeypatch):
    """A worker entrypoint should process a queued job and finalize its checkpoint."""
    worker = getattr(sync_jobs, "process_sync_job", None)
    assert worker is not None, "Expected a worker entrypoint for queued sync jobs"

    db = FakeSession()
    user = _fake_user()
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="scheduler",
    )
    ingest_run_id = uuid.uuid4()
    finished_at = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    latest_activity = datetime(2026, 4, 4, 11, 30, tzinfo=timezone.utc)

    def fake_fetch(db_arg, user_arg, test_run=False):  # pylint: disable=unused-argument
        assert user_arg.id == user.id
        assert test_run is False
        return SimpleNamespace(id=ingest_run_id, summary={"activities": 3}, finished_at=finished_at)

    monkeypatch.setattr(sync_jobs.garmin_ingest, "fetch_garmin_recent", fake_fetch)
    monkeypatch.setattr(
        sync_jobs.garmin_activity,
        "get_latest_activity_start_time",
        lambda db_arg, user_arg: latest_activity,
    )

    result = worker(db, job)

    assert result.job.status == "completed"
    assert result.job.ingest_run_id == ingest_run_id
    checkpoint = sync_jobs.get_sync_checkpoint(db, user_id=user.id, provider="garmin")
    assert checkpoint is not None
    assert checkpoint.status == "ok"
    assert checkpoint.last_ingest_run_id == ingest_run_id
    assert checkpoint.cursor_json["latest_activity_start_time"] == latest_activity.isoformat()


def test_worker_failure_marks_job_and_checkpoint_predictably(monkeypatch):
    """A worker entrypoint should persist a failed job and error checkpoint."""
    worker = getattr(sync_jobs, "process_sync_job", None)
    assert worker is not None, "Expected a worker entrypoint for queued sync jobs"

    db = FakeSession()
    user = _fake_user()
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="scheduler",
    )

    def fake_fetch(db_arg, user_arg, test_run=False):  # pylint: disable=unused-argument
        raise HTTPException(status_code=502, detail="Garmin fetch failed")

    monkeypatch.setattr(sync_jobs.garmin_ingest, "fetch_garmin_recent", fake_fetch)

    with pytest.raises(HTTPException):
        worker(db, job)

    jobs = [item for item in db.items if isinstance(item, SyncJob)]
    checkpoints = [item for item in db.items if isinstance(item, SyncCheckpoint)]
    assert jobs and jobs[0].status == "failed"
    assert jobs[0].error_json["message"] == "Garmin fetch failed"
    assert checkpoints and checkpoints[0].status == "error"
    assert checkpoints[0].error_json["status_code"] == 502


def test_scheduler_batch_enqueues_work_instead_of_executing_inline(monkeypatch):
    """The scheduler should dispatch work to the worker layer, not call inline sync."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession(
        [
            UserProviderToken(
                user_id=uuid.uuid4(),
                provider="garmin_scraper",
                access_token_encrypted=b"token",
            )
        ]
    )
    calls = []

    monkeypatch.setattr(
        garmin_scheduler,
        "enqueue_sync_job",
        lambda db_arg, user_id, provider, trigger, **_kwargs: calls.append((db_arg, user_id, provider, trigger))
        or SimpleNamespace(id=uuid.uuid4(), status="queued"),
    )

    result = garmin_scheduler.fetch_all(db)

    assert result["status"] == "queued"
    assert result["queued"] == 1
    assert calls == [(db, db.items[0].user_id, "garmin", "scheduler")]
