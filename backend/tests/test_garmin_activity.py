"""Tests for Garmin activity write-path edge cases."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.garmin import activity


class FakeWriteApi:
    """Capture Influx write payloads for assertions."""

    def __init__(self):
        self.calls = []

    def write(self, **kwargs):
        self.calls.append(kwargs)


class FakeInfluxClient:
    """Minimal Influx client stub for GPS write tests."""

    def __init__(self):
        self.default_bucket = "bucket"
        self.org = "org"
        self.write_api_client = FakeWriteApi()

    def write_api(self):
        return self.write_api_client


def test_write_activity_gps_serializes_datetime_fields():
    """Datetime fields should be normalized before sending points to Influx."""
    influx_client = FakeInfluxClient()
    user = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4())
    recorded_at = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)

    count = activity.write_activity_gps(
        influx_client,
        user,
        run,
        "ingest-tag",
        123,
        [{"time": 1, "fields": {"timestamp": recorded_at, "HeartRate": 145}}],
    )

    assert count == 1
    written = influx_client.write_api_client.calls[0]["record"][0]
    assert written["fields"]["timestamp"] == recorded_at.isoformat()
    assert written["fields"]["HeartRate"] == 145
