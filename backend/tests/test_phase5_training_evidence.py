"""Phase 5 contracts for bounded history and athlete-to-self evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from app.models import Activity
from app.services.journey import build_activity_detail, build_journey


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *criteria):
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


def make_activity(user_id, now, days_ago, distance_m, sport="run", duration_seconds=3600):
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=now - timedelta(days=days_ago),
        duration_seconds=duration_seconds,
        distance_m=distance_m,
        sport=sport,
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={"name": f"{sport.title()} session"},
    )


def test_journey_bounds_activity_rows_without_changing_full_window_totals():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    activities = [
        make_activity(athlete_id, now, day, 1000 + day)
        for day in range(60)
    ]

    result = build_journey(
        FakeSession(activities),
        athlete_id,
        window="90d",
        activity_page=2,
        activity_page_size=10,
        now=now,
    )

    assert len(result["activities"]) == 10
    assert result["activity_pagination"] == {
        "page": 2,
        "page_size": 10,
        "total_items": 60,
        "total_pages": 6,
        "from": 11,
        "to": 20,
    }
    assert result["totals"]["activity_count"] == 60
    assert result["totals"]["distance_m"] == sum(1000 + day for day in range(60))


def test_journey_compares_selected_window_with_previous_equal_window():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    current = [
        make_activity(athlete_id, now, 5, 10000),
        make_activity(athlete_id, now, 10, 20000),
    ]
    previous = [
        make_activity(athlete_id, now, 35, 5000),
        make_activity(athlete_id, now, 40, 10000),
    ]

    result = build_journey(
        FakeSession(current + previous),
        athlete_id,
        window="30d",
        sport="run",
        now=now,
    )

    comparison = result["comparison"]
    assert comparison["basis"] == "Previous 30 days"
    assert comparison["current"]["activity_count"] == 2
    assert comparison["previous"]["activity_count"] == 2
    assert comparison["current"]["distance_m"] == 30000
    assert comparison["previous"]["distance_m"] == 15000
    assert comparison["changes"]["distance_percent"] == 100.0


def test_activity_detail_compares_only_prior_same_sport_owned_history():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    current = make_activity(athlete_id, now, 0, 15000, "running")
    prior_one = make_activity(athlete_id, now, 5, 10000, "run")
    prior_two = make_activity(athlete_id, now, 10, 14000, "treadmill_running")
    bike = make_activity(athlete_id, now, 3, 90000, "cycling")
    other = make_activity(other_id, now, 2, 99000, "running")

    result = build_activity_detail(
        FakeSession([current, prior_one, prior_two, bike, other]),
        athlete_id,
        current.id,
    )

    comparison = result["comparison"]
    assert comparison["state"] == "available"
    assert comparison["sample_size"] == 2
    assert comparison["distance_median"] == 12000
    assert comparison["distance_percent_vs_median"] == 25.0
    assert comparison["basis"].startswith("Previous 2 same-sport")
