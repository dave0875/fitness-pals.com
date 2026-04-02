"""Tests for metrics summary resilience."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models import DataSource
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

    monkeypatch.setattr("app.routes.metrics.get_user_datasource", lambda *_args, **_kwargs: ds)
    monkeypatch.setattr("app.routes.metrics.get_influx_client_for_user", lambda *_args, **_kwargs: InfluxClientStub())

    result = summary(user=user, db=object())

    assert result["mileage"] == {"30d": 0.0, "60d": 0.0, "90d": 0.0}
    assert result["pace_histogram"] == []
