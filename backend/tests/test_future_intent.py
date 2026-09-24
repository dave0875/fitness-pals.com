"""Athlete Orbit Phase 3 future-intent contract tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

from app.models import AthleteGoal
from app.services.athlete_intent import build_future_intent


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *_conditions):
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    def __init__(self, items=()):
        self.items = list(items)

    def query(self, model):
        return FakeQuery(item for item in self.items if isinstance(item, model))


def goal(user_id, now, **overrides):
    values = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "goal_type": "marathon",
        "phase": "build",
        "target_date": date(2026, 11, 1),
        "intent_json": {
            "target_distance": "Marathon",
            "target_performance": "3:15",
            "intent_source": "onboarding",
        },
        "created_at": now - timedelta(days=20),
        "updated_at": now - timedelta(days=1),
    }
    values.update(overrides)
    return AthleteGoal(**values)


def test_future_intent_is_athlete_scoped_explicit_and_does_not_infer_target_time():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()

    result = build_future_intent(
        FakeSession(
            [
                goal(other_id, now, intent_json={"target_time_seconds": 6000}),
                goal(athlete_id, now),
            ]
        ),
        athlete_id,
        now=now,
    )

    assert result["state"] == "known"
    intent = result["intent"]
    assert intent["goal"]["type"] == "marathon"
    assert intent["target"]["performance"] == "3:15"
    assert intent["target"]["time_seconds"] is None
    assert intent["provenance"]["kind"] == "explicit"
    assert intent["provenance"]["canonical_model"] == "athlete_goal"
    assert intent["derived"]["days_to_target"] == 38
    assert intent["derived"]["provenance"]["kind"] == "derived"
    assert "does not predict" in intent["derived"]["caveat"]


def test_structured_target_time_is_preserved_only_when_explicitly_supplied():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    row = goal(
        athlete_id,
        now,
        intent_json={
            "target_performance": "Break 3:15",
            "target_time_seconds": 11700,
            "intent_source": "today",
        },
    )

    intent = build_future_intent(FakeSession([row]), athlete_id, now=now)["intent"]

    assert intent["target"]["time_seconds"] == 11700
    assert "target.time_seconds" in intent["provenance"]["explicit_fields"]


def test_non_race_goal_remains_first_class_without_fabricated_event_fields():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    row = goal(
        athlete_id,
        now,
        goal_type="healthy_activity",
        phase="maintenance",
        target_date=None,
        intent_json={
            "target_performance": "Move consistently",
            "custom_goal": "Stay active through winter",
        },
    )

    intent = build_future_intent(FakeSession([row]), athlete_id, now=now)["intent"]

    assert intent["goal"]["type"] == "healthy_activity"
    assert intent["target"]["date"] is None
    assert intent["target"]["time_seconds"] is None
    assert intent["derived"]["days_to_target"] is None
    assert intent["derived"]["target_date_relation"] is None


def test_missing_goal_is_unknown_not_an_inferred_default():
    result = build_future_intent(
        FakeSession(),
        uuid.uuid4(),
        now=datetime(2026, 9, 24, 12, tzinfo=timezone.utc),
    )

    assert result["state"] == "unknown"
    assert result["intent"] is None
    assert result["error"] is None
