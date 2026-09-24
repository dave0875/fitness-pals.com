"""Contract tests for provider-neutral whole-training evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from app.models import Activity, ActivityTrainingEvidence
from app.services.activity_quality import valid_distance_m
from app.services.training_evidence import (
    evidence_payload,
    normalize_training_evidence,
    sport_family,
    sport_matches,
    summarize_activities,
)


def activity(sport: str, duration: int | None, distance: float | None = None) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        start_time=datetime(2026, 9, 24, 12, tzinfo=timezone.utc),
        duration_seconds=duration,
        distance_m=distance,
        sport=sport,
        status="completed",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={},
    )


def evidence(item: Activity, **values) -> ActivityTrainingEvidence:
    defaults = {
        "activity_id": item.id,
        "modality": sport_family(item.sport),
        "provider_sport": item.sport,
        "source_provider": "garmin_archive",
    }
    defaults.update(values)
    return ActivityTrainingEvidence(**defaults)


def test_sport_taxonomy_is_deliberate_and_unknown_is_not_running():
    assert sport_family("running") == "running"
    assert sport_family("cycling", "indoor_cycling") == "cycling"
    assert sport_family("strength_training") == "strength"
    assert sport_family("hiking") == "walking_hiking"
    assert sport_family("lap_swimming") == "swimming"
    assert sport_family("indoor_rowing") == "rowing"
    assert sport_family("elliptical") == "indoor_cardio"
    assert sport_family("pickleball") == "other"
    assert sport_matches("trail_running", "run")
    assert not sport_matches("pickleball", "run")


def test_normalization_preserves_observed_cross_training_fields_and_unknowns():
    normalized = normalize_training_evidence(
        {
            "activityType": "cycling",
            "subSport": "indoor_cycling",
            "duration": 4500,
            "trainingEvidence": {
                "provider_sport": "cycling",
                "provider_sub_sport": "indoor_cycling",
                "avg_heart_rate": 146,
                "max_heart_rate": 172,
                "avg_power": 211,
                "normalized_power": 228,
                "structure": {"laps": [{"index": 0, "timer_seconds": 600}]},
            },
            "sourceObjectId": "drive-1",
            "sourceContentHash": "sha256",
        },
        "garmin_archive",
    )

    assert normalized["modality"] == "cycling"
    assert normalized["avg_heart_rate"] == 146
    assert normalized["avg_power"] == 211
    assert normalized["normalized_power"] == 228
    assert normalized["max_power"] is None
    assert normalized["calories"] is None
    assert normalized["structure_json"]["laps"][0]["timer_seconds"] == 600
    assert normalized["source_object_id"] == "drive-1"
    assert "avg_power" in normalized["observed_fields"]
    assert normalized["derived_fields"] == ["modality"]


def test_strength_is_training_without_becoming_zero_mileage():
    strength = activity("strength_training", 2700, 21474836)
    row = evidence(
        strength,
        modality="strength",
        avg_heart_rate=128,
        structure_json={"sets": [{"index": 0, "repetitions": 10}]},
    )

    payload = evidence_payload(strength, row)
    summary = summarize_activities([strength], {strength.id: row})

    assert valid_distance_m(strength.distance_m, strength.sport) is None
    assert payload["modality"] == "strength"
    assert payload["avg_heart_rate"] == 128
    assert payload["structure"]["sets"][0]["repetitions"] == 10
    assert summary["duration_seconds"] == 2700
    assert summary["strength_sessions"] == 1
    assert summary["cross_training_sessions"] == 1


def test_whole_training_summary_keeps_modalities_and_incomparable_units_separate():
    run = activity("running", 3600, 10000)
    ride = activity("cycling", 4500, 30000)
    lift = activity("strength_training", 2400, None)
    rows = {
        ride.id: evidence(ride, modality="cycling", avg_heart_rate=142, avg_power=205),
        lift.id: evidence(lift, modality="strength"),
    }

    summary = summarize_activities([run, ride, lift], rows)
    by_modality = {item["modality"]: item for item in summary["by_modality"]}

    assert summary["activity_count"] == 3
    assert summary["duration_seconds"] == 10500
    assert by_modality["running"]["duration_seconds"] == 3600
    assert by_modality["cycling"]["duration_seconds"] == 4500
    assert by_modality["strength"]["duration_seconds"] == 2400
    assert summary["hr_supported_workouts"] == 1
    assert summary["power_supported_cycling_workouts"] == 1
    assert "distance_m" not in summary
    assert "training_load" not in summary


def test_absent_duration_hr_and_power_remain_unavailable_not_zero():
    workout = activity("elliptical", None)
    row = evidence(workout, modality="indoor_cardio")

    payload = evidence_payload(workout, row)
    summary = summarize_activities([workout], {workout.id: row})

    assert payload["avg_heart_rate"] is None
    assert payload["avg_power"] is None
    assert summary["duration_seconds"] is None
    assert summary["hr_supported_duration_seconds"] is None
    assert summary["power_supported_cycling_duration_seconds"] is None
