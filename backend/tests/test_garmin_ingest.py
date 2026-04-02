"""Targeted tests for Garmin ingest edge cases."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

from app.models import UserProviderToken
from app.services import garmin_ingest
from app.services.providers import ProviderTokenDetails, save_user_provider_token


class FakeSession:
    """Minimal SQLAlchemy-like session stub for Garmin ingest tests."""

    def __init__(self):
        self.items = []

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        return obj

    def rollback(self):
        return None

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for provider-token lookups."""

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
            if getattr(condition.operator, "__name__", "") == "is_" and getattr(right, "__visit_name__", "") == "null":
                return left is None
            return condition.operator(left, right)
        return True


class ReadOnlyUsernameClient:
    """Stub garth client exposing a read-only username property."""

    oauth1_token = None

    @property
    def username(self):
        return "readonly"


def test_fetch_garmin_recent_tolerates_read_only_client_username(monkeypatch):
    """Scraper ingest should not fail when the garth client username is read-only."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    run = SimpleNamespace(id=uuid.uuid4(), summary=None)

    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="access-token",
            refresh_token="refresh-token",
        ),
    )

    monkeypatch.setattr(
        garmin_ingest,
        "_build_garth_client",
        lambda access_token, token_secret=None: ReadOnlyUsernameClient(),
    )
    monkeypatch.setattr(
        garmin_ingest,
        "_ensure_provider_user_id",
        lambda db_arg, token_row, client: "2883204",
    )
    monkeypatch.setattr(garmin_ingest, "_maybe_get_influx_client", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(garmin_ingest.activity_svc, "get_latest_activity_start_time", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(garmin_ingest.activity_svc, "fetch_activity_list", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(garmin_ingest, "fetch_health_bundle", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(garmin_ingest, "_persist_sleep_sessions_from_bundle", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(garmin_ingest, "build_aggregate_summary", lambda bundle: {})
    monkeypatch.setattr(
        garmin_ingest.dedupe,
        "record_ingest_run",
        lambda *_args, **_kwargs: run,
    )
    monkeypatch.setattr(
        garmin_ingest.dedupe,
        "finish_ingest_run",
        lambda _db, run_obj, status, summary: setattr(run_obj, "summary", {"status": status, **summary}),
    )

    result = garmin_ingest.fetch_garmin_recent(db, user)

    assert result is run
    assert result.summary == {
        "status": "completed",
        "activities": 0,
        "activity_gps_written": 0,
        "timeseries_points": 0,
        "sleep_daily": 0,
        "test_run": False,
    }
