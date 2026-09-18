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
