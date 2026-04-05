"""Slice 6 red tests for provider adapter formalization."""

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
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("GARMIN_MODE", "oauth")


from app.providers.garmin import GarminProvider
from app.services import sync_jobs


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


class FakeSession:
    """Minimal SQLAlchemy-like session stub for orchestration tests."""

    def __init__(self):
        self.items = []

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

    def get(self, _model, _ident):
        return None


def _fake_user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=None)


def test_process_sync_job_uses_provider_adapter_contract(monkeypatch):
    """Sync orchestration should resolve and dispatch through a provider adapter."""
    db = FakeSession()
    user = _fake_user()
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=user.id,
        provider="garmin",
        trigger="manual",
    )

    adapter_calls = []
    helper_calls = []
    finished_at = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    ingest_run_id = uuid.uuid4()

    class FakeGarminAdapter:
        name = "garmin"

        def refresh_access_token(
            self, refresh_token
        ):  # pragma: no cover - contract shape only
            adapter_calls.append(("refresh_access_token", refresh_token))
            return {"access_token": "new-access"}

        def fetch_daily_stats(
            self, access_token, **kwargs
        ):  # pragma: no cover - contract shape only
            adapter_calls.append(("fetch_daily_stats", access_token, kwargs))
            return {"bridge": "daily"}

        def fetch_activities(
            self, access_token, since=None, **kwargs
        ):  # pragma: no cover - contract shape only
            adapter_calls.append(("fetch_activities", access_token, since, kwargs))
            return {"bridge": "activities"}

    monkeypatch.setattr(
        sync_jobs,
        "get_provider_adapter",
        lambda provider: (
            adapter_calls.append(("lookup", provider)) or FakeGarminAdapter()
        ),
        raising=False,
    )
    monkeypatch.setattr(
        sync_jobs.garmin_ingest,
        "fetch_garmin_recent",
        lambda *_args, **_kwargs: (
            helper_calls.append("fetch_garmin_recent")
            or SimpleNamespace(
                id=ingest_run_id, summary={"activities": 1}, finished_at=finished_at
            )
        ),
    )
    monkeypatch.setattr(
        sync_jobs.garmin_activity,
        "get_latest_activity_start_time",
        lambda *_args, **_kwargs: datetime(2026, 4, 1, 11, 30, tzinfo=timezone.utc),
    )

    result = sync_jobs.process_sync_job(db, job)

    assert helper_calls == []
    assert adapter_calls and adapter_calls[0] == ("lookup", "garmin")
    assert any(call[0] == "fetch_activities" for call in adapter_calls)
    assert result.job.status == "completed"


def test_garmin_provider_bridge_methods_forward_through_adapter_seam(monkeypatch):
    """The Garmin adapter should be able to delegate to a bridge client behind the seam."""
    bridge_calls = []

    class FakeBridge:
        def fetch_activities(self, access_token, since=None, **kwargs):
            bridge_calls.append(("fetch_activities", access_token, since, kwargs))
            return {"activities": [{"id": "bridge-1", "provider": "garmin"}]}

        def fetch_daily_stats(self, access_token, **kwargs):
            bridge_calls.append(("fetch_daily_stats", access_token, kwargs))
            return {"steps": 1234}

    monkeypatch.setattr(
        GarminProvider,
        "bridge_client",
        FakeBridge(),
        raising=False,
    )

    provider = GarminProvider()
    result = provider.fetch_activities("access-token", since="2026-04-01")

    assert bridge_calls == [("fetch_activities", "access-token", "2026-04-01", {})]
    assert result["activities"][0]["provider"] == "garmin"


def test_process_sync_job_rejects_unknown_provider_with_clean_orchestration_error():
    """Unsupported providers should fail cleanly at the orchestration boundary."""
    db = FakeSession()
    job = sync_jobs.enqueue_sync_job(
        db,
        user_id=uuid.uuid4(),
        provider="polar",
        trigger="manual",
    )

    with pytest.raises(HTTPException) as exc:
        sync_jobs.process_sync_job(db, job)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported sync provider: polar"
