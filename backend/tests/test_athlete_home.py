"""Tests for the canonical athlete-home read model."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

from app.models import Activity, DossierArtifact, DossierJob, SleepSession, SyncCheckpoint
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
    assert result["readiness"]["state"] == "unknown"
    assert result["training_consistency"]["state"] == "available"


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


def test_fresh_workout_does_not_mask_stale_sleep_or_enable_readiness():
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    sleep = SleepSession(
        id=uuid.uuid4(), user_id=athlete_id, provider="garmin",
        daily_sleep_id=20260902, calendar_date=date(2026, 9, 2),
        summary_json={"sleepTimeSeconds": 27000, "sleepScores": {"overall": 82}},
    )
    result = build_athlete_home(
        FakeSession([make_activity(athlete_id, now, 1, 10000), sleep]),
        athlete_id, goal="marathon", now=now,
    )
    assert result["freshness"]["signals"]["activities"]["state"] == "fresh"
    assert result["freshness"]["signals"]["sleep"]["state"] == "stale"
    assert result["freshness"]["state"] == "partial"
    assert result["recovery"]["state"] == "stale"
    assert result["readiness"]["score"] is None
    assert result["training_consistency"]["score"] is not None


def test_strength_sentinel_does_not_become_zero_mile_consistency_score():
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    strength = make_activity(athlete_id, now, 1, 21474836, "strength_training")
    result = build_athlete_home(FakeSession([strength]), athlete_id, goal=None, now=now)
    assert result["recent_activities"][0]["distance_m"] is None
    assert result["training_consistency"]["score"] is None


def test_athlete_home_uses_sleep_and_sync_freshness():
    """Fresh canonical sleep and checkpoint data should produce a fresh view."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    sleep = SleepSession(
        id=uuid.uuid4(),
        user_id=athlete_id,
        provider="garmin",
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
        provider="garmin",
        status="succeeded",
        last_synced_at=now - timedelta(hours=2),
    )
    db = FakeSession([make_activity(athlete_id, now, 1, 12000), sleep, checkpoint])
    db.items[0].metadata_json["intensity"] = "easy"

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


def test_generic_coaching_cta_navigates_to_todays_run_decision():
    """A recommendation CTA must open the plan instead of an empty chat box."""
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    activities = [
        make_activity(athlete_id, now, days_ago, 5000)
        for days_ago in (1, 2, 3, 4)
    ]

    result = build_athlete_home(
        FakeSession(activities), athlete_id, goal="consistency", now=now
    )

    assert result["coaching"]["next_action"] == {
        "label": "Open today's run",
        "href": "/dashboard#todays-run",
    }
    assert result["coaching"]["insight"] == "Make the next session serve your goal."
    assert "last seven days" not in result["coaching"]["explanation"]


def test_athlete_home_links_latest_owned_dossier_and_ignores_other_athletes():
    """The home card must link only to the signed-in athlete's newest artifact."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    owned = DossierArtifact(
        id=uuid.uuid4(),
        user_id=athlete_id,
        job_id=uuid.uuid4(),
        version=2,
        snapshot_hash="a" * 64,
        content_json={
            "title": "Marathon coaching dossier",
            "summary": "Owned summary",
            "freshness": "partial",
        },
        data_through=now - timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    other = DossierArtifact(
        id=uuid.uuid4(),
        user_id=other_id,
        job_id=uuid.uuid4(),
        version=99,
        snapshot_hash="b" * 64,
        content_json={"title": "Other athlete's dossier"},
        created_at=now,
        updated_at=now,
    )

    result = build_athlete_home(
        FakeSession([make_activity(athlete_id, now, 1, 8000), owned, other]),
        athlete_id,
        goal="marathon",
        now=now,
    )

    assert result["dossier"]["state"] == "completed"
    assert result["dossier"]["title"] == "Marathon coaching dossier"
    assert result["dossier"]["action"]["href"] == f"/dossiers/{owned.id}"
    assert "Other athlete" not in str(result["dossier"])


def test_athlete_home_prioritizes_active_dossier_generation():
    """An active immutable generation request should remain visible after navigation."""
    now = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    job = DossierJob(
        id=uuid.uuid4(),
        user_id=athlete_id,
        status="generating",
        snapshot_hash="c" * 64,
        request_json={"filters": {"window": "90d", "sport": "run", "goal": "marathon"}},
        created_at=now,
        updated_at=now,
    )

    result = build_athlete_home(FakeSession([job]), athlete_id, goal=None, now=now)

    assert result["dossier"]["state"] == "generating"
    assert result["dossier"]["action"]["href"] == "/dossiers"
