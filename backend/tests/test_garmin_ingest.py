"""Targeted tests for Garmin ingest edge cases."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

from app.models import Activity, ActivitySource
from app.services.garmin import activity as garmin_activity
from app.services import garmin_ingest
from app.services.providers import ProviderTokenDetails, save_user_provider_token


class FakeSession:
    """Minimal SQLAlchemy-like session stub for Garmin ingest tests."""

    def __init__(self):
        self.items = []

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
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

    def order_by(self, *_args, **_kwargs):
        return self

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
            if (
                getattr(condition.operator, "__name__", "") == "is_"
                and getattr(right, "__visit_name__", "") == "null"
            ):
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
    monkeypatch.setattr(
        garmin_ingest, "_maybe_get_influx_client", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        garmin_ingest.activity_svc,
        "get_latest_activity_start_time",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        garmin_ingest.activity_svc, "fetch_activity_list", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        garmin_ingest, "fetch_health_bundle", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        garmin_ingest,
        "_persist_sleep_sessions_from_bundle",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(garmin_ingest, "build_aggregate_summary", lambda bundle: {})
    monkeypatch.setattr(
        garmin_ingest.dedupe,
        "record_ingest_run",
        lambda *_args, **_kwargs: run,
    )
    monkeypatch.setattr(
        garmin_ingest.dedupe,
        "finish_ingest_run",
        lambda _db, run_obj, status, summary: setattr(
            run_obj, "summary", {"status": status, **summary}
        ),
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


def test_fetch_garmin_recent_rejects_expired_connection_lease(monkeypatch):
    """The browser-issued Garmin grant must be renewed after 30 days."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            metadata={"auth_scheme": "garmin_connect_sso"},
        ),
    )

    with pytest.raises(HTTPException) as exc:
        garmin_ingest.fetch_garmin_recent(db, user)

    assert exc.value.status_code == 410
    assert "reauth" in str(exc.value.detail).lower()


def test_persist_activity_summaries_does_not_store_raw_garmin_payload_in_metadata():
    """Canonical metadata should keep provider payloads trimmed, not verbatim."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4())
    payload = [
        {
            "id": "garmin-act-123",
            "activityName": "Morning Run",
            "activityType": "running",
            "startTimeGMT": "2026-04-02T12:00:00Z",
            "distance": 10000.4,
            "duration": 3600.4,
            "deviceName": "Forerunner 965",
            "sourceType": "GARMIN_CONNECT",
            "raw_payload": {"metricDescriptors": [{"key": "directHeartRate"}]},
        }
    ]

    garmin_activity.persist_activity_summaries(db, user, run, payload)

    created = next(item for item in db.items if isinstance(item, Activity))
    assert created.metadata_json["provider_activity_id"] == "garmin-act-123"
    assert created.metadata_json != payload[0]
    assert "raw_payload" not in created.metadata_json
    assert "deviceName" not in created.metadata_json
    assert "sourceType" not in created.metadata_json


def test_persist_activity_summaries_persists_activity_source_identity():
    """Canonical activity writes should create a provenance row alongside them."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4())
    payload = [
        {
            "id": "garmin-act-456",
            "activityName": "Lunch Ride",
            "activityType": "cycling",
            "startTimeGMT": "2026-04-02T13:00:00Z",
            "distance": 25000.0,
            "duration": 5400.0,
            "ownerId": "garmin-user-9",
        }
    ]

    garmin_activity.persist_activity_summaries(db, user, run, payload)

    activities = [item for item in db.items if isinstance(item, Activity)]
    sources = [item for item in db.items if isinstance(item, ActivitySource)]

    assert len(activities) == 1
    assert len(sources) == 1
    assert sources[0].activity_id == activities[0].id
    assert sources[0].provider == "garmin"
    assert sources[0].provider_activity_id == "garmin-act-456"


def test_persist_activity_summaries_marks_sentinel_and_missing_distance_unknown():
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4())
    payload = [
        {"id": "strength-sentinel", "activityType": "strength_training", "distance": 21474836},
        {"id": "run-missing", "activityType": "running"},
        {"id": "run-valid", "activityType": "running", "distance": 5000},
    ]
    garmin_activity.persist_activity_summaries(db, user, run, payload)
    activities = {item.fingerprint_hash: item for item in db.items if isinstance(item, Activity)}
    assert activities["strength-sentinel"].distance_m is None
    assert activities["run-missing"].distance_m is None
    assert activities["run-valid"].distance_m == 5000
    sources = [item for item in db.items if isinstance(item, ActivitySource)]
    assert len(sources) == 3
    assert sources[0].chosen_fields["source_distance_m"] == 21474836


def test_persist_activity_summaries_is_idempotent_for_replayed_payload_window():
    """Replaying the same Garmin payload/window should not create duplicate canonical rows."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4())
    payload = [
        {
            "id": "garmin-act-789",
            "activityName": "Tempo Run",
            "activityType": "running",
            "startTimeGMT": "2026-04-02T14:00:00Z",
            "distance": 8000.0,
            "duration": 2400.0,
        }
    ]

    garmin_activity.persist_activity_summaries(db, user, run, payload)
    garmin_activity.persist_activity_summaries(db, user, run, payload)

    activities = [item for item in db.items if isinstance(item, Activity)]
    assert len(activities) == 1
    assert activities[0].fingerprint_hash == "garmin-act-789"
