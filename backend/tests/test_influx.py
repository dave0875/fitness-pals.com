"""Unit tests for operator-owned Influx service configuration."""

from unittest.mock import patch

from app.services.influx import get_operator_influx_client


def test_operator_influx_client_uses_environment_only(monkeypatch):
    """Influx mirroring must be configured by operators, not datasource rows."""
    monkeypatch.setenv("RUNTRAINER_INFLUX_URL", "http://influxdb.internal:8086")
    monkeypatch.setenv("INFLUXDB_ORG", "operator-org")
    monkeypatch.setenv("INFLUXDB_DATABASE", "operator-bucket")
    monkeypatch.setenv("INFLUXDB_TOKEN", "operator-token")

    with patch("app.services.influx.InfluxDBClient") as client_cls:
        client = get_operator_influx_client()

    client_cls.assert_called_once_with(
        url="http://influxdb.internal:8086",
        org="operator-org",
        token="operator-token",
    )
    assert client.default_bucket == "operator-bucket"


def test_operator_influx_client_accepts_legacy_password_env(monkeypatch):
    """Existing deployments may continue using the operator password variable."""
    monkeypatch.delenv("INFLUXDB_TOKEN", raising=False)
    monkeypatch.setenv("RUNTRAINER_INFLUX_URL", "http://influxdb:8086")
    monkeypatch.setenv("INFLUXDB_PASSWORD", "operator-password")

    with patch("app.services.influx.InfluxDBClient") as client_cls:
        get_operator_influx_client()

    assert client_cls.call_args.kwargs["token"] == "operator-password"
