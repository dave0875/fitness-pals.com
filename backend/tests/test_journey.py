"""Tests for the athlete-scoped journey explorer read model."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import uuid

from fastapi import HTTPException
import pytest

from app.models import Activity, ActivitySource, SleepSession
from app.services.journey import build_activity_detail, build_journey


class FakeQuery:
    """Small query facade for canonical journey tests."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *criteria):
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    """Return model-specific in-memory rows."""

    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


def make_activity(user_id, now, days_ago, distance_m, sport="run", intensity=None):
    """Build one canonical activity."""
    metadata = {"name": f"{sport.title()} session"}
    if intensity:
        metadata["intensity"] = intensity
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=now - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport=sport,
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json=metadata,
    )


def make_sleep(user_id, calendar_date, seconds=27000):
    """Build one canonical sleep record."""
    return SleepSession(
        id=uuid.uuid4(),
        user_id=user_id,
        provider="pulsai",
        daily_sleep_id=int(calendar_date.strftime("%Y%m%d")),
        calendar_date=calendar_date,
        summary_json={"sleepTimeSeconds": seconds},
    )


def test_journey_totals_reconcile_with_visible_filtered_activities():
    """Selected-window totals equal the athlete-owned activities shown."""
    now = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    run = make_activity(athlete_id, now, 2, 10000, "run", "easy")
    ride = make_activity(athlete_id, now, 5, 20000, "bike", "moderate")
    old_run = make_activity(athlete_id, now, 120, 50000, "run", "hard")
    other = make_activity(other_id, now, 1, 99000, "run", "hard")
    duplicate_source = ActivitySource(
        id=uuid.uuid4(),
        activity_id=run.id,
        provider="pulsai",
        provider_activity_id="same-canonical-run",
        decision="duplicate",
        chosen_fields={"upstream_provider": "garmin"},
        raw_payload={"private_url": "https://private.pulsai.me/secret"},
    )
    db = FakeSession([run, ride, old_run, other, duplicate_source])

    result = build_journey(
        db,
        athlete_id,
        window="30d",
        sport="run",
        goal="marathon",
        now=now,
    )

    assert [item["id"] for item in result["activities"]] == [str(run.id)]
    assert result["totals"]["activity_count"] == len(result["activities"]) == 1
    assert result["totals"]["distance_m"] == sum(
        item["distance_m"] for item in result["activities"]
    )
    assert result["totals"]["duration_seconds"] == sum(
        item["duration_seconds"] for item in result["activities"]
    )
    assert sum(week["activity_count"] for week in result["weekly_summaries"]) == 1
    assert sum(month["activity_count"] for month in result["monthly_summaries"]) == 1
    assert result["goal"]["label"] == "Marathon"


def test_journey_marks_missing_signals_unknown_and_stale():
    """Missing recovery/intensity remain unknown and old data is marked stale."""
    now = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    old_activity = make_activity(athlete_id, now, 10, 5000)
    old_activity.metadata_json = {"name": "Old run"}

    result = build_journey(
        FakeSession([old_activity]),
        athlete_id,
        window="30d",
        sport="all",
        goal=None,
        now=now,
    )

    assert result["freshness"]["state"] == "stale"
    assert "sleep" in result["freshness"]["missing"]
    assert "intensity" in result["freshness"]["missing"]
    assert result["totals"]["intensity_distribution"] is None
    assert result["weekly_summaries"][0]["average_sleep_hours"] is None


def test_journey_activity_detail_is_private_and_redacts_raw_provenance():
    """Detail returns safe source labels without raw payloads or credentials."""
    now = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    activity = make_activity(athlete_id, now, 1, 16093.44, "run", "moderate")
    source = ActivitySource(
        id=uuid.uuid4(),
        activity_id=activity.id,
        provider="pulsai",
        provider_activity_id="garmin-private-id",
        decision="merged",
        chosen_fields={
            "upstream_provider": "garmin",
            "source_timestamp": "2026-08-02T12:00:00+00:00",
            "private_url": "https://private.pulsai.me/secret",
        },
        raw_payload={
            "access_token": "secret-token",
            "private_url": "https://private.pulsai.me/secret",
        },
    )

    result = build_activity_detail(
        FakeSession([activity, source]),
        athlete_id,
        activity.id,
    )
    serialized = json.dumps(result)

    assert result["activity"]["id"] == str(activity.id)
    assert result["provenance"] == [
        {
            "provider": "pulsai",
            "upstream_provider": "garmin",
            "source_timestamp": "2026-08-02T12:00:00+00:00",
        }
    ]
    assert "secret-token" not in serialized
    assert "private.pulsai.me" not in serialized
    assert "garmin-private-id" not in serialized


def test_journey_activity_detail_rejects_cross_athlete_access():
    """An activity owned by another athlete is indistinguishable from missing."""
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    activity = make_activity(
        other_id,
        datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        1,
        5000,
    )

    with pytest.raises(HTTPException) as exc_info:
        build_activity_detail(FakeSession([activity]), athlete_id, activity.id)

    assert exc_info.value.status_code == 404
