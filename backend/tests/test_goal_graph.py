"""Athlete Orbit Phase 4 canonical Goal Graph contracts."""

from __future__ import annotations

from datetime import date, datetime, timezone
import uuid

from fastapi import HTTPException
import pytest

from app.models import AthleteGoal, AthleteGoalEvent, AthleteGoalObjective, NextSessionPlan
from app.services.athlete_goal_graph import (
    build_goal_graph, save_goal_event, save_goal_objective, sync_primary_event_from_goal,
)


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *_criteria):
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    def __init__(self, items=()):
        self.items = list(items)
        self.commits = 0

    def query(self, model):
        return FakeQuery(item for item in self.items if isinstance(item, model))

    def add(self, item):
        if item not in self.items:
            self.items.append(item)

    def commit(self):
        self.commits += 1


def root(user_id):
    return AthleteGoal(
        id=uuid.uuid4(), user_id=user_id, goal_type="marathon", phase="build",
        target_date=date(2026, 11, 1),
        intent_json={"target_distance": "Marathon", "target_performance": "3:15"},
    )


def event(user_id, goal_id, *, role, label, when, priority=50, state="planned", seconds=None):
    return AthleteGoalEvent(
        id=uuid.uuid4(), user_id=user_id, goal_id=goal_id, role=role,
        event_type="marathon" if role == "primary" else "race", label=label,
        event_date=when, distance_label="Marathon" if role == "primary" else "10 miles",
        target_performance=None, target_time_seconds=seconds, priority=priority,
        lifecycle_state=state, provenance_json={"kind": "explicit", "source": "goal_graph"},
    )


def test_graph_keeps_primary_supporting_calendar_objectives_and_athlete_isolation():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    goal = root(athlete_id)
    primary = event(athlete_id, goal.id, role="primary", label="NYC Marathon", when=date(2026, 11, 1), priority=1)
    tuneup = event(athlete_id, goal.id, role="supporting", label="Staten Island Half", when=date(2026, 10, 11), priority=20)
    earlier = event(athlete_id, goal.id, role="supporting", label="Bronx 10 Mile", when=date(2026, 9, 19), priority=30)
    objective = AthleteGoalObjective(
        id=uuid.uuid4(), user_id=athlete_id, goal_id=goal.id, event_id=primary.id,
        label="Complete final long run", target_date=date(2026, 10, 18), priority=10,
        lifecycle_state="planned", details_json={},
        provenance_json={"kind": "explicit", "source": "goal_graph"},
    )
    foreign_goal = root(other_id)
    foreign = event(other_id, foreign_goal.id, role="primary", label="Foreign race", when=date(2026, 10, 1))
    graph = build_goal_graph(
        FakeSession([goal, primary, tuneup, earlier, objective, foreign_goal, foreign]),
        athlete_id, now=now,
    )
    assert graph["state"] == "known"
    assert graph["primary_event"]["label"] == "NYC Marathon"
    assert [item["label"] for item in graph["supporting_events"]] == ["Bronx 10 Mile", "Staten Island Half"]
    assert graph["primary_event"]["derived"]["days_to_event"] == 38
    assert graph["objectives"][0]["event_id"] == str(primary.id)
    assert "Foreign race" not in str(graph)


def test_terminal_primary_is_retained_but_not_active_primary():
    athlete_id = uuid.uuid4()
    goal = root(athlete_id)
    completed = event(athlete_id, goal.id, role="primary", label="Completed race", when=date(2026, 8, 22), state="completed")
    graph = build_goal_graph(
        FakeSession([goal, completed]), athlete_id,
        now=datetime(2026, 9, 24, 12, tzinfo=timezone.utc),
    )
    assert graph["primary_event"] is None
    assert graph["calendar"] == []
    assert graph["events"][0]["lifecycle"]["state"] == "completed"


def test_target_time_stays_unknown_unless_explicitly_structured():
    athlete_id = uuid.uuid4()
    goal = root(athlete_id)
    primary = event(athlete_id, goal.id, role="primary", label="NYC Marathon", when=date(2026, 11, 1))
    graph = build_goal_graph(
        FakeSession([goal, primary]), athlete_id,
        now=datetime(2026, 9, 24, 12, tzinfo=timezone.utc),
    )
    assert graph["primary_event"]["target_time_seconds"] is None
    assert "target.time_seconds" not in graph["primary_event"]["provenance"]["explicit_fields"]


def test_promoting_primary_preserves_old_event_syncs_root_and_invalidates_plan():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    goal = root(athlete_id)
    old = event(athlete_id, goal.id, role="primary", label="Old primary", when=date(2026, 10, 1))
    plan = NextSessionPlan(
        id=uuid.uuid4(), user_id=athlete_id, goal_id=goal.id, status="accepted",
        session_purpose="Easy aerobic support", scheduled_for=date(2026, 9, 24),
        recommendation_json={}, rationale_json={},
    )
    db = FakeSession([goal, old, plan])
    graph = save_goal_event(
        db, athlete_id, event_id=None, role="primary", event_type="marathon",
        label="NYC Marathon", event_date=date(2026, 11, 1), distance="Marathon",
        target_performance="Break 3:15", target_time_seconds=11700, priority=1,
        lifecycle_state="planned", now=now,
    )
    assert old.role == "supporting"
    assert graph["primary_event"]["label"] == "NYC Marathon"
    assert goal.target_date == date(2026, 11, 1)
    assert goal.intent_json["target_time_seconds"] == 11700
    assert plan.status == "skipped"
    assert plan.feedback_json == {"reason": "goal_graph_primary_updated"}


def test_objective_cannot_link_to_another_athletes_event():
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    goal = root(athlete_id)
    foreign_goal = root(other_id)
    foreign_event = event(other_id, foreign_goal.id, role="primary", label="Foreign", when=date(2026, 11, 1))
    db = FakeSession([goal, foreign_goal, foreign_event])
    with pytest.raises(HTTPException) as exc_info:
        save_goal_objective(
            db, athlete_id, objective_id=None, event_id=foreign_event.id, label="Tune up",
            target_date=date(2026, 10, 1), priority=10, lifecycle_state="planned", details={},
        )
    assert exc_info.value.status_code == 404


def test_legacy_goal_write_materializes_primary_without_parsing_performance_text():
    athlete_id = uuid.uuid4()
    goal = root(athlete_id)
    goal.intent_json = {
        "target_distance": "Marathon", "target_performance": "3:15", "intent_source": "today",
    }
    db = FakeSession([goal])
    created = sync_primary_event_from_goal(
        db, athlete_id, goal, now=datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    )
    assert created is not None
    assert created.role == "primary"
    assert created.target_performance == "3:15"
    assert created.target_time_seconds is None
