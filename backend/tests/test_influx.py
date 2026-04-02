"""Unit tests for the Influx service helpers."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pydantic import ValidationError

from app.models import DataSource
from app.routes.datasource import InfluxConnectRequest, verify_influx
from app.services.influx import assert_safe_influx_config, get_influx_client_for_user
from app.utils.security import encrypt_token


def test_get_influx_client_for_user():
    """Influx client helper should return a configured client."""
    fake_db = MagicMock()
    user_id = uuid.uuid4()
    ds = DataSource(
        user_id=user_id,
        influx_url="http://localhost:8086",
        influx_org="test",
        influx_bucket="bucket",
        token_encrypted=encrypt_token("token"),
    )
    fake_db.query.return_value.filter.return_value.first.return_value = ds
    with patch("app.services.influx.InfluxDBClient") as client_cls:
        client = get_influx_client_for_user(fake_db, user_id)
        client_cls.assert_called_once()
        assert client is client_cls.return_value


def test_influx_connect_request_rejects_unsafe_bucket():
    """Validator should block buckets that could break Flux queries."""
    with pytest.raises(ValidationError):
        InfluxConnectRequest(
            url="http://localhost:8086",
            org="valid-org",
            bucket="bad;drop()",
            token="secret",
        )


def test_assert_safe_influx_config_rejects_invalid_names():
    """Existing configs with unsafe names should raise before querying."""
    ds = DataSource(
        user_id=uuid.uuid4(),
        influx_url="http://localhost:8086",
        influx_org="bad name",
        influx_bucket="bucket\nx",
        token_encrypted=encrypt_token("token"),
    )
    with pytest.raises(ValueError):
        assert_safe_influx_config(ds)


def test_verify_influx_queries_measurements_for_bucket(monkeypatch):
    """Verify endpoint should query schema.measurements with the configured bucket."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = MagicMock()
    ds = DataSource(
        user_id=user_id,
        influx_url="http://localhost:8086",
        influx_org="test",
        influx_bucket="bucket",
        token_encrypted=encrypt_token("token"),
    )
    query_api = MagicMock()
    client = MagicMock()
    client.query_api.return_value = query_api

    monkeypatch.setattr("app.routes.datasource.get_user_datasource", lambda *_args, **_kwargs: ds)
    monkeypatch.setattr("app.routes.datasource.get_influx_client_for_user", lambda *_args, **_kwargs: client)

    result = verify_influx(user=user, db=db)

    assert result == {"status": "ok"}
    query_api.query.assert_called_once()
    assert 'schema.measurements(bucket: "bucket")' in query_api.query.call_args.kwargs["query"]
