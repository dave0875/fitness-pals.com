"""Tests for the canonical athlete-home read model."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

from app.models import Activity, SleepSession, SyncCheckpoint
from app.services.athlete_home import build_athlete_home


class FakeQuery:
    """Small query facade for read-model tests."""

    def __init__(self, items):
        self.items = list(items)

    def all(self):
        return list(self.items)


class FakeSession:
    """Return model-specific in-memory rows."""

    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


def make_activity(user_id, now, days_ago, distance_m, sport="run"):
    """Build a canonical activity owned by one athlete."""
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=now - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport=sport,
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={"name": "Morning run"},
    )


def test_athlete_home_isolates_canonical_data_by_user():
    """Another athlete's activity must never enter the home response."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db = FakeSession(
        [
            make_activity(athlete_id, now, 1, 10000),
            make_activity(other_id, now, 1, 50000),
        ]
    )

    result = build_athlete_home(db, athlete_id, goal="marathon", now=now)

    assert len(result["recent_activities"]) == 1
    assert result["recent_activities"][0]["distance_m"] == 10000
    assert result["goal"]["label"] == "Marathon"
    assert result["readiness"]["state"] == "available"


def test_athlete_home_marks_missing_recovery_unknown_not_zero():
    """Absent sleep history should be explicit rather than represented as zero."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    db = FakeSession([make_activity(athlete_id, now, 1, 8000)])

    result = build_athlete_home(db, athlete_id, goal="consistency", now=now)

    assert result["recovery"] == {
        "state": "unknown",
        "label": "Recovery data unavailable",
        "sleep_hours": None,
        "sleep_score": None,
        "overnight_hrv": None,
    }
    assert result["freshness"]["state"] == "partial"
    assert "sleep" in result["freshness"]["missing"]


def test_athlete_home_uses_sleep_and_sync_freshness():
    """Fresh canonical sleep and checkpoint data should produce a fresh view."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    sleep = SleepSession(
        id=uuid.uuid4(),
        user_id=athlete_id,
        provider="pulsai",
        daily_sleep_id=20260802,
        calendar_date=date(2026, 8, 2),
        summary_json={
            "sleepTimeSeconds": 27000,
            "sleepScores": {"overall": 82},
            "avgOvernightHrv": 41,
        },
    )
    checkpoint = SyncCheckpoint(
        id=uuid.uuid4(),
        user_id=athlete_id,
        provider="pulsai",
        status="succeeded",
        last_synced_at=now - timedelta(hours=2),
    )
    db = FakeSession([make_activity(athlete_id, now, 1, 12000), sleep, checkpoint])

    result = build_athlete_home(db, athlete_id, goal="marathon", now=now)

    assert result["freshness"]["state"] == "fresh"
    assert result["recovery"]["sleep_hours"] == 7.5
    assert result["recovery"]["sleep_score"] == 82
    assert result["recovery"]["overnight_hrv"] == 41


def test_athlete_home_stale_and_empty_states_are_actionable():
    """Stale and empty histories should explain the next useful action."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    stale = build_athlete_home(
        FakeSession([make_activity(athlete_id, now, 10, 5000)]),
        athlete_id,
        goal=None,
        now=now,
    )
    empty = build_athlete_home(FakeSession([]), athlete_id, goal=None, now=now)

    assert stale["freshness"]["state"] == "stale"
    assert stale["coaching"]["next_action"]["href"] == "/welcome"
    assert empty["state"] == "empty"
    assert empty["readiness"]["state"] == "unknown"
    assert empty["dossier"]["state"] == "not_generated"
