"""Tests for metrics summary resilience."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import uuid
from types import SimpleNamespace

import pytest

from app.models import Activity, DataSource
from app.routes.metrics import RaceReadinessRequest, race_readiness, summary
from app.utils.security import encrypt_token


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

    def first(self):
        return self.data[0] if self.data else None

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    @staticmethod
    def _resolve_value(side, item):
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
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

    def add(self, _obj):
        return None

    def commit(self):
        return None


def _make_activity(user_id, days_ago, distance_m):
    """Create activity data relative to the current rolling metrics window."""
    return Activity(
        user_id=user_id,
        start_time=datetime.now(timezone.utc) - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport="run",
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}-{distance_m}",
        metadata_json={},
    )


def test_summary_ignores_legacy_influx_datasource():
    """A persisted athlete URL must never influence product metric reads."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    ds = DataSource(
        user_id=user_id,
        influx_url="http://169.254.169.254/latest/meta-data",
        influx_org="default",
        influx_bucket="GarminStats",
        token_encrypted=encrypt_token("token"),
    )

    db = FakeSession([ds, _make_activity(user_id, 4, 7000.0)])

    result = summary(user=user, db=db)

    assert result["mileage"] == {"30d": 7000.0, "60d": 7000.0, "90d": 7000.0}
    assert result["pace_histogram"] == []


def test_summary_uses_canonical_activity_data():
    """Summary should derive mileage and long-run values from canonical Postgres data."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [
            _make_activity(user_id, 5, 5000.0),
            _make_activity(user_id, 20, 10000.0),
            _make_activity(user_id, 50, 20000.0),
        ]
    )

    result = summary(user=user, db=db)

    assert result["mileage"] == {"30d": 15000.0, "60d": 35000.0, "90d": 35000.0}
    assert result["average_weekly_mileage"] == pytest.approx(2916.6666666666665)
    assert result["long_run_max"] == 20000.0
    assert result["pace_histogram"] == []
    assert result["training_load"] == []


def test_summary_isolates_athlete_rows():
    """Canonical metric reads must exclude another athlete's activity rows."""
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [_make_activity(user_id, 2, 8000.0), _make_activity(other_user_id, 1, 42000.0)]
    )

    result = summary(user=user, db=db)

    assert result["mileage"]["30d"] == 8000.0
    assert result["long_run_max"] == 8000.0


def test_race_readiness_uses_canonical_activity_mileage_and_isolates_user():
    """Race readiness should use only the athlete's last 30 days in Postgres."""
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [
            _make_activity(user_id, 2, 10000.0),
            _make_activity(user_id, 35, 50000.0),
            _make_activity(other_user_id, 1, 100000.0),
        ]
    )

    result = race_readiness(
        RaceReadinessRequest(
            race_type="marathon", race_date=datetime.now(timezone.utc) + timedelta(days=30)
        ),
        user=user,
        db=db,
    )

    expected_miles = 10000.0 / 1609.34
    assert result["readiness"] == pytest.approx(expected_miles / 400 * 100)
    assert f"{expected_miles:.1f} miles" in result["commentary"]
