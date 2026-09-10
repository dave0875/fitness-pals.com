"""Tests for the canonical Postgres metrics read model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.models import Activity, DataSource
from app.routes.metrics import RaceReadinessRequest, race_readiness, summary
from app.services.activity_summary import build_canonical_summary


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for canonical read-model tests."""

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

    @staticmethod
    def _resolve_value(side, item):
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        if hasattr(side, "value"):
            return side.value
        return side

    def _matches(self, condition, item):
        left = self._resolve_value(getattr(condition, "left", None), item)
        right = self._resolve_value(getattr(condition, "right", None), item)
        operator = getattr(condition, "operator", None)
        if operator is None:
            return True
        try:
            return operator(left, right)
        except Exception:
            return True


class FakeSession:
    """Minimal SQLAlchemy-like session stub for canonical read-model tests."""

    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


class FailingSession:
    """Canonical store stub that simulates an unavailable database."""

    def query(self, _model):
        raise RuntimeError("postgres unavailable")


def _make_activity(user_id, now, days_ago, distance_m):
    """Create activity data relative to a deterministic metrics window."""
    return Activity(
        user_id=user_id,
        start_time=now - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport="run",
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}-{distance_m}",
        metadata_json={},
    )


def test_summary_ignores_legacy_influx_and_isolates_canonical_athlete_data():
    """A legacy datasource must not affect product reads or leak another athlete."""
    now = datetime.now(timezone.utc)
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    legacy_datasource = DataSource(
        user_id=user_id,
        influx_url="http://127.0.0.1:8086",
        influx_org="legacy",
        influx_bucket="legacy",
        token_encrypted="unused",
    )
    db = FakeSession(
        [
            legacy_datasource,
            _make_activity(user_id, now, 2, 5000.0),
            _make_activity(user_id, now, 20, 10000.0),
            _make_activity(other_user_id, now, 1, 999999.0),
        ]
    )

    result = summary(user=user, db=db)

    assert result["source"] == "canonical_postgres"
    assert result["state"] == "fresh"
    assert result["generated_at"]
    assert result["data_through"] == (now - timedelta(days=2)).isoformat()
    assert result["stale_after"] == (now + timedelta(days=1)).isoformat()
    assert result["mileage"] == {"30d": 15000.0, "60d": 15000.0, "90d": 15000.0}
    assert result["long_run_max"] == 10000.0
    assert result["metric_states"]["hrv_avg"] == "unknown"


def test_canonical_summary_marks_old_data_stale_without_discarding_values():
    """Old canonical values remain visible with an explicit stale state."""
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    user_id = uuid.uuid4()
    result = build_canonical_summary(
        FakeSession([_make_activity(user_id, now, 10, 8000.0)]),
        user_id,
        now=now,
    )

    assert result["state"] == "stale"
    assert result["generated_at"] == now.isoformat()
    assert result["data_through"] == (now - timedelta(days=10)).isoformat()
    assert result["stale_after"] == (now - timedelta(days=7)).isoformat()
    assert result["mileage"]["30d"] == 8000.0
    assert result["long_run_max"] == 8000.0


def test_canonical_summary_marks_missing_data_unknown_instead_of_zero():
    """No canonical history is unknown, not a fabricated zero-mile history."""
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    result = build_canonical_summary(FakeSession([]), uuid.uuid4(), now=now)

    assert result["state"] == "unknown"
    assert result["generated_at"] == now.isoformat()
    assert result["data_through"] is None
    assert result["stale_after"] is None
    assert result["mileage"] == {"30d": None, "60d": None, "90d": None}
    assert result["average_weekly_mileage"] is None
    assert result["long_run_max"] is None
    assert result["hrv_avg"] is None
    assert result["pace_histogram"] is None
    assert result["training_load"] is None


def test_canonical_summary_reports_postgres_error_without_fabricated_values():
    """Canonical query failure is explicit and safe for product consumers."""
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    result = build_canonical_summary(FailingSession(), uuid.uuid4(), now=now)

    assert result["state"] == "error"
    assert result["generated_at"] == now.isoformat()
    assert result["data_through"] is None
    assert result["mileage"]["30d"] is None
    assert result["error"] == {
        "code": "canonical_read_failed",
        "message": "Canonical fitness data is temporarily unavailable.",
    }


def test_race_readiness_uses_only_canonical_postgres():
    """Race readiness shares the canonical athlete-scoped read model."""
    now = datetime.now(timezone.utc)
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [
            _make_activity(user_id, now, 2, 40000.0),
            _make_activity(other_user_id, now, 1, 400000.0),
        ]
    )

    result = race_readiness(
        RaceReadinessRequest(
            race_type="half marathon",
            race_date=now + timedelta(days=30),
        ),
        user=user,
        db=db,
    )

    miles_30 = 40000.0 / 1609.34
    assert result["source"] == "canonical_postgres"
    assert result["state"] == "fresh"
    assert result["data_through"] == (now - timedelta(days=2)).isoformat()
    assert result["readiness"] == pytest.approx(miles_30 / 400 * 100)
    assert "24.9 miles" in result["commentary"]
