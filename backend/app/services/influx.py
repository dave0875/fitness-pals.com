"""Operator-owned InfluxDB configuration for optional timeseries mirroring."""

from __future__ import annotations

import os
import re
from typing import cast
from urllib.parse import urlparse

from influxdb_client import InfluxDBClient

from app.types import InfluxClientLike

_SAFE_INFLUX_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_influx_identifier(value: str, field_name: str) -> str:
    """Validate an operator value before embedding it in a Flux query."""
    if not value or not _SAFE_INFLUX_NAME.fullmatch(value):
        raise ValueError(
            f"Invalid {field_name}; only letters, numbers, '.', '_', and '-' are allowed."
        )
    return value


def _operator_influx_url() -> str:
    url = (
        os.environ.get("RUNTRAINER_INFLUX_URL")
        or os.environ.get("RUNTRAINER_INFLUX_DEFAULT_URL")
        or os.environ.get("INFLUXDB_URL")
        or "http://influxdb:8086"
    )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Operator Influx URL must be an absolute HTTP(S) URL")
    return url.rstrip("/")


def get_operator_influx_client() -> InfluxClientLike:
    """Create an Influx client exclusively from trusted deployment settings."""
    url = _operator_influx_url()
    org = validate_influx_identifier(
        os.environ.get("INFLUXDB_ORG") or "default", "org"
    )
    bucket = validate_influx_identifier(
        os.environ.get("INFLUXDB_DATABASE") or "GarminStats", "bucket"
    )
    token = os.environ.get("INFLUXDB_TOKEN") or os.environ.get("INFLUXDB_PASSWORD") or ""
    client = InfluxDBClient(url=url, org=org, token=token)
    client.default_bucket = bucket  # type: ignore[attr-defined]
    return cast(InfluxClientLike, client)
