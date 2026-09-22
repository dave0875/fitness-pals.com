"""Tests for Garmin FIT SDK normalization and activity timeseries parsing."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.garmin import activity_fit
from app.services.garmin.fit_sdk import normalized_developer_fields


def test_normalized_developer_fields_preserve_names_and_scaling():
    message = {"developer_fields": {3: 250, 7: [100, 200]}}
    descriptions = {
        3: {"name": "Vertical Oscillation", "scale": 10, "offset": 0},
        7: {"name": "Custom Metric", "scale": 100, "offset": 1},
    }

    result = normalized_developer_fields(message, descriptions)

    assert result["vertical_oscillation"] == 25.0
    assert result["custom_metric"] == [0.0, 1.0]


def test_activity_timeseries_uses_sdk_records_hrv_and_developer_fields(monkeypatch):
    recorded_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def fake_decode(_content):
        return (
            {
                "record_mesgs": [
                    {
                        "timestamp": recorded_at,
                        "heart_rate": 151,
                        "cadence": 89.6,
                        "temperature": 21.6,
                        "position_lat": 2**30,
                        "position_long": -(2**30),
                        "developer_fields": {1: 92},
                    }
                ],
                "hrv_mesgs": [{"time": [0.8, 1.0]}],
            },
            {1: {"name": "Running Power", "scale": 1, "offset": 0}},
        )

    monkeypatch.setattr(activity_fit, "decode_fit_bytes", fake_decode)

    samples = activity_fit.parse_fit_file_to_timeseries(
        b"fit",
        activity_id=123,
        activity_name="SDK Run",
        start_time=None,
    )

    record = samples[0]
    assert record["time"] == int(recorded_at.timestamp() * 1_000_000_000)
    assert record["fields"]["HeartRate"] == 151
    assert record["fields"]["Cadence"] == 90
    assert record["fields"]["Temperature"] == 22
    assert record["fields"]["Latitude"] == 90.0
    assert record["fields"]["Longitude"] == -90.0
    assert record["fields"]["running_power"] == 92.0
    assert record["fields"]["ActivityID"] == 123
    assert record["fields"]["ActivityName"] == "SDK Run"

    assert [sample["fields"]["RR"] for sample in samples[1:]] == [800.0, 1000.0]
