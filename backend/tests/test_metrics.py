"""Tests for metrics summary resilience."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import uuid
from types import SimpleNamespace

import pytest

from app.models import Activity, DataSource
from app.routes.metrics import summary
from app.utils.security import encrypt_token


class QueryApiStub:
    """Return canned Flux results and fail only on the histogram query."""

    def query(self, org, query):  # pylint: disable=unused-argument
        if "histogram(" in query:
            raise ValueError("histogram bin overflow")
        return []


class InfluxClientStub:
    """Minimal Influx client stub for summary tests."""

    def query_api(self):
        return QueryApiStub()


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
    return Activity(
        user_id=user_id,
        start_time=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc)
        - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport="run",
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}-{distance_m}",
        metadata_json={},
    )


def test_summary_tolerates_histogram_query_failure(monkeypatch):
    """Summary should degrade gracefully when the pace histogram query fails."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    ds = DataSource(
        user_id=user_id,
        influx_url="http://localhost:8086",
        influx_org="default",
        influx_bucket="GarminStats",
        token_encrypted=encrypt_token("token"),
    )

    monkeypatch.setattr(
        "app.routes.metrics.get_user_datasource", lambda *_args, **_kwargs: ds
    )
    monkeypatch.setattr(
        "app.routes.metrics.get_influx_client_for_user",
        lambda *_args, **_kwargs: InfluxClientStub(),
    )

    result = summary(user=user, db=object())

    assert result["mileage"] == {"30d": 0.0, "60d": 0.0, "90d": 0.0}
    assert result["pace_histogram"] == []


def test_summary_uses_canonical_activity_data_when_influx_datasource_is_missing(
    monkeypatch,
):
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

    monkeypatch.setattr(
        "app.routes.metrics.get_user_datasource", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "app.routes.metrics.get_influx_client_for_user",
        lambda *_args, **_kwargs: pytest.fail(
            "summary should not require Influx when canonical data exists"
        ),
    )

    result = summary(user=user, db=db)

    assert result["mileage"] == {"30d": 15000.0, "60d": 35000.0, "90d": 35000.0}
    assert result["average_weekly_mileage"] == pytest.approx(2916.6666666666665)
    assert result["long_run_max"] == 20000.0
    assert result["pace_histogram"] == []
    assert result["training_load"] == []


def test_summary_remains_resilient_when_influx_is_absent(monkeypatch):
    """Canonical read-model behavior should not fall over just because Influx is missing."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession([_make_activity(user_id, 2, 8000.0)])

    monkeypatch.setattr(
        "app.routes.metrics.get_user_datasource", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "app.routes.metrics.get_influx_client_for_user",
        lambda *_args, **_kwargs: pytest.fail(
            "canonical metrics should not depend on Influx"
        ),
    )

    result = summary(user=user, db=db)

    assert result["mileage"]["30d"] == 8000.0
    assert result["long_run_max"] == 8000.0
