"""Guard the offline Garmin export transformations used for backfilling."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_garmin_drive_export.py"
SPEC = importlib.util.spec_from_file_location("backfill_garmin_drive_export", SCRIPT)
assert SPEC and SPEC.loader
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


def test_garmin_summary_units_and_profile_id(tmp_path: Path) -> None:
    (tmp_path / "dave_1_summarizedActivities.json").write_text(
        '[{"summarizedActivitiesExport": [{"activityId": 42, "userProfileId": 7, '
        '"startTimeGmt": 1720000000000, "duration": 3600000, '
        '"distance": 1000000, "sportType": "RUNNING"}]}]',
        encoding="utf-8",
    )
    activity, = backfill.load_activity_summaries(tmp_path, 7)
    assert activity.duration_seconds == 3600
    assert activity.distance_m == 10000
    assert activity.sport == "running"
    assert activity.start_time == datetime.fromtimestamp(1720000000, tz=timezone.utc)


def test_sleep_normalization_preserves_raw_export_fields() -> None:
    raw = {
        "calendarDate": "2026-09-02", "deepSleepSeconds": 600,
        "lightSleepSeconds": 1200, "remSleepSeconds": 300,
        "sleepScores": {"overallScore": 66},
    }
    normalized = backfill._normalize_sleep(raw)
    assert normalized["sleepTimeSeconds"] == 2100
    assert normalized["sleepScore"] == 66
    assert normalized["sleepScores"] == raw["sleepScores"]
    assert backfill._sleep_fields(normalized)["sleepScore"] == 66
    assert "sleepScore" not in raw


def test_window_only_sleep_does_not_invent_measured_sleep() -> None:
    raw = {
        "calendarDate": "2016-06-11",
        "sleepStartTimestampGMT": "2016-06-11T02:00:00.0",
        "sleepEndTimestampGMT": "2016-06-11T10:00:00.0",
    }
    normalized = backfill._normalize_sleep(raw)
    assert "sleepTimeSeconds" not in normalized
    fields = backfill._sleep_fields(normalized)
    assert fields["record_present"] == 1
    assert fields["sleep_window_seconds"] == 28800


def test_recent_fit_and_samples_use_shared_garmin_sdk(monkeypatch, tmp_path: Path) -> None:
    from app.services.garmin import fit_sdk

    fit_path = tmp_path / "2026-09-21-12-00-00.fit"
    fit_path.write_bytes(b"fake-fit")
    started = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def fake_decode(content: bytes):
        assert content == b"fake-fit"
        return (
            {
                "session_mesgs": [{
                    "start_time": started,
                    "total_timer_time": 3600.0,
                    "total_distance": 10000.0,
                    "sport": "running",
                }],
                "record_mesgs": [{
                    "timestamp": started,
                    "heart_rate": 150,
                    "power": 280,
                    "position_lat": 2**30,
                    "position_long": -(2**30),
                }],
            },
            {},
        )

    monkeypatch.setattr(fit_sdk, "decode_fit_bytes", fake_decode)

    activities, included = backfill.load_recent_fits(
        tmp_path,
        datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
    )
    assert included == [fit_path]
    assert len(activities) == 1
    assert activities[0].distance_m == 10000.0
    assert activities[0].duration_seconds == 3600.0
    assert activities[0].sport == "running"

    from uuid import UUID

    points = backfill._fit_sample_points(
        fit_path,
        UUID("00000000-0000-0000-0000-000000000001"),
    )
    assert len(points) == 1
    assert points[0]["fields"]["heart_rate"] == 150.0
    assert points[0]["fields"]["power"] == 280.0
    assert points[0]["fields"]["position_lat"] == 90.0
    assert points[0]["fields"]["position_long"] == -90.0
