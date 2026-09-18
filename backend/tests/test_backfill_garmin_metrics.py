"""Offline validation of Garmin performance-metric backfill points."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_garmin_metrics.py"
SPEC = importlib.util.spec_from_file_location("backfill_garmin_metrics", SCRIPT)
assert SPEC and SPEC.loader
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


def test_metric_points_preserve_payload_and_separate_same_day_rows(tmp_path: Path) -> None:
    rows = [
        {"userProfilePK": 7, "calendarDate": 1720000000000, "score": 61, "level": "GOOD"},
        {"userProfilePK": 7, "calendarDate": 1720000000000, "score": 62, "level": "GREAT"},
    ]
    (tmp_path / "TrainingReadinessDTO_20240101_20241231_7.json").write_text(json.dumps(rows))
    points, counts = backfill.load_metric_points(tmp_path, 7, UUID(int=1))
    assert counts == {"TrainingReadinessDTO": 2}
    assert points[0]["time"] != points[1]["time"]
    assert points[0]["tags"]["user_id"] == str(UUID(int=1))
    assert points[0]["fields"]["n_score"] == 61
    assert points[0]["fields"]["s_level"] == "GOOD"
    assert json.loads(points[0]["fields"]["payload_json"]) == rows[0]


def test_metric_profile_mismatch_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "EnduranceScore_20240101_20241231_7.json").write_text(
        json.dumps([{"userProfilePK": 8, "calendarDate": "2024-01-01"}])
    )
    with pytest.raises(ValueError, match="profile mismatch"):
        backfill.load_metric_points(tmp_path, 7, UUID(int=1))
