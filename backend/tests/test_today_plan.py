"""Tests for the persisted, goal-aware Today's run coaching loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

from fastapi import HTTPException
import pytest

from app.models import Activity, AthleteGoal, NextSessionPlan, SleepSession
from app.services.today_plan import (
    apply_plan_action,
    build_today_context,
    build_today_plan,
    create_next_plan,
    save_goal,
)


class FakeQuery:
    """Return model-specific rows from the in-memory test store."""

    def __init__(self, items):
        self.items = list(items)

    def all(self):
        return list(self.items)

    def filter(self, *_criteria):
        return self


class FakeSession:
    """Small persistence facade for coaching-loop unit tests."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.commits = 0

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def add(self, item):
        if item not in self.items:
            self.items.append(item)

    def flush(self):
        return None

    def commit(self):
        self.commits += 1


def run(user_id, when, miles, minutes, *, intensity=None):
    """Build one canonical run with optional trusted intensity metadata."""
    metadata = {"name": "Run"}
    if intensity:
        metadata["intensity"] = intensity
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=when,
        duration_seconds=minutes * 60,
        distance_m=miles * 1609.344,
        sport="run",
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json=metadata,
    )


def test_goal_and_recovery_phase_are_persisted_without_assuming_current_goal():
    """An explicit post-race/recovery phase drives the recommendation."""
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession([run(athlete_id, now - timedelta(days=2), 3.5, 31)])

    result = save_goal(
        db,
        athlete_id,
        goal_type="marathon",
        phase="recovery",
        target_date=date(2026, 8, 22),
        now=now,
    )

    stored = next(item for item in db.items if isinstance(item, AthleteGoal))
    assert stored.user_id == athlete_id
    assert result["goal"] == {
        "type": "marathon",
        "label": "Marathon",
        "phase": "recovery",
        "phase_label": "Post-race / recovery",
        "target_date": "2026-08-22",
    }
    assert result["plan"]["session_purpose"] == "Recovery movement"
    assert result["plan"]["status"] == "recommended"


def test_recommendation_cites_exact_recent_sessions_and_uses_ranges():
    """The September production evidence should be visible, not reduced to an aggregate."""
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession(
        [
            run(athlete_id, datetime(2026, 9, 16, 10, tzinfo=timezone.utc), 3.5, 31),
            run(athlete_id, datetime(2026, 9, 14, 10, tzinfo=timezone.utc), 4.0, 37),
        ]
    )

    result = save_goal(
        db,
        athlete_id,
        goal_type="marathon",
        phase="build",
        target_date=None,
        now=now,
    )

    plan = result["plan"]
    assert [item["summary"] for item in plan["evidence"]] == [
        "Sep 16: 3.5 mi in 31 min.",
        "Sep 14: 4.0 mi in 37 min.",
    ]
    assert plan["duration_minutes"] == {"min": 25, "max": 30}
    assert plan["distance_miles"] == {"min": 2.5, "max": 3.5}
    assert "Easy to conversational" in plan["effort_range"]
    assert "pace" not in plan["effort_range"].lower()
    assert plan["scheduled_for"] == "2026-09-18"


def test_stale_and_missing_signals_are_uncertainty_not_readiness():
    """The plan consumes, rather than duplicates, per-signal freshness semantics."""
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    stale_sleep = SleepSession(
        id=uuid.uuid4(),
        user_id=athlete_id,
        provider="garmin",
        daily_sleep_id=20260902,
        calendar_date=date(2026, 9, 2),
        summary_json={"sleepTimeSeconds": 27000, "sleepScores": {"overall": 82}},
    )
    db = FakeSession(
        [run(athlete_id, now - timedelta(days=2), 3.5, 31), stale_sleep]
    )

    result = save_goal(
        db,
        athlete_id,
        goal_type="consistency",
        phase="maintenance",
        target_date=None,
        now=now,
    )

    uncertainty = " ".join(result["plan"]["uncertainty"])
    assert "Sleep is stale" in uncertainty
    assert "Intensity is unknown" in uncertainty
    assert "not a medical or readiness assessment" in uncertainty
    assert "sleep score is 82" not in " ".join(result["plan"]["rationale"]).lower()


def test_goal_prompt_precedes_recommendation_when_no_goal_is_persisted():
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    other_goal = AthleteGoal(
        id=uuid.uuid4(),
        user_id=other_id,
        goal_type="marathon",
        phase="build",
    )
    result = build_today_plan(
        FakeSession([other_goal, run(athlete_id, now, 3.0, 30)]),
        athlete_id,
        now=now,
    )

    assert result["state"] == "goal_required"
    assert result["goal"] is None
    assert result["plan"] is None
    assert "recovery" in result["goal_options"]


def test_plan_persistence_is_user_isolated_and_cross_user_action_is_not_found():
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    plan = NextSessionPlan(
        id=uuid.uuid4(),
        user_id=owner_id,
        goal_id=uuid.uuid4(),
        status="recommended",
        session_purpose="Easy aerobic support",
        scheduled_for=date(2026, 9, 18),
        recommendation_json={"duration_minutes": {"min": 25, "max": 30}},
        rationale_json={"evidence": [], "rationale": [], "uncertainty": []},
    )
    db = FakeSession([plan])

    with pytest.raises(HTTPException) as exc_info:
        apply_plan_action(db, other_id, plan.id, action="accept", payload={})

    assert exc_info.value.status_code == 404
    assert plan.status == "recommended"


def test_dashboard_to_feedback_to_next_decision_state_transition():
    """Exercise the complete next-action lifecycle that the dashboard exposes."""
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession(
        [
            run(athlete_id, datetime(2026, 9, 16, 10, tzinfo=timezone.utc), 3.5, 31),
            run(athlete_id, datetime(2026, 9, 14, 10, tzinfo=timezone.utc), 4.0, 37),
        ]
    )
    recommended = save_goal(
        db,
        athlete_id,
        goal_type="consistency",
        phase="maintenance",
        target_date=None,
        now=now,
    )
    plan_id = uuid.UUID(recommended["plan"]["id"])

    adjusted = apply_plan_action(
        db,
        athlete_id,
        plan_id,
        action="adjust",
        payload={
            "scheduled_for": "2026-09-19",
            "duration_minutes": {"min": 20, "max": 25},
            "distance_miles": {"min": 2.0, "max": 2.5},
            "effort_range": "Easy and conversational",
        },
        now=now,
    )
    assert adjusted["plan"]["status"] == "adjusted"
    accepted = apply_plan_action(
        db, athlete_id, plan_id, action="accept", payload={}, now=now
    )
    assert accepted["plan"]["status"] == "accepted"
    completed = apply_plan_action(
        db,
        athlete_id,
        plan_id,
        action="complete",
        payload={"perceived_effort": "as_expected", "note": "Felt controlled."},
        now=now + timedelta(days=1),
    )
    assert completed["state"] == "completed"
    assert completed["plan"]["feedback"] == {
        "perceived_effort": "as_expected",
        "note": "Felt controlled.",
    }
    assert completed["next_decision_available"] is True

    next_result = create_next_plan(
        db, athlete_id, now=now + timedelta(days=1)
    )
    assert next_result["state"] == "recommended"
    assert next_result["plan"]["id"] != str(plan_id)
    assert any(
        "previous session felt as expected" in item
        for item in next_result["plan"]["rationale"]
    )


def test_skipped_plan_returns_to_a_next_decision():
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession([run(athlete_id, now - timedelta(days=2), 3.5, 31)])
    recommended = save_goal(
        db,
        athlete_id,
        goal_type="recovery",
        phase="recovery",
        target_date=None,
        now=now,
    )
    plan_id = uuid.UUID(recommended["plan"]["id"])

    skipped = apply_plan_action(
        db,
        athlete_id,
        plan_id,
        action="skip",
        payload={"note": "Travel day"},
        now=now,
    )

    assert skipped["state"] == "skipped"
    assert skipped["next_decision_available"] is True



def test_today_context_exposes_rolling_week_trajectory_and_safe_match():
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession(
        [
            run(athlete_id, datetime(2026, 9, 16, 10, tzinfo=timezone.utc), 3.5, 31),
            run(athlete_id, datetime(2026, 9, 14, 10, tzinfo=timezone.utc), 4.0, 37),
        ]
    )
    recommended = save_goal(
        db,
        athlete_id,
        goal_type="marathon",
        phase="build",
        target_date=date(2026, 11, 1),
        now=now,
    )
    plan_id = uuid.UUID(recommended["plan"]["id"])
    apply_plan_action(db, athlete_id, plan_id, action="accept", payload={}, now=now)
    matching = run(athlete_id, datetime(2026, 9, 18, 18, tzinfo=timezone.utc), 3.0, 27)
    db.add(matching)

    context = build_today_context(db, athlete_id, now=now)

    assert len(context["week"]["days"]) == 7
    assert any(day["is_today"] for day in context["week"]["days"])
    assert context["trajectory"]["goal"]["type"] == "marathon"
    assert context["trajectory"]["days_to_target"] == 44
    assert context["trajectory"]["last_7_days"]["runs"] == 3
    assert context["match"]["id"] == str(matching.id)
    assert "Same scheduled day" in context["match"]["basis"]


def test_move_is_distinct_from_modifying_the_session_prescription():
    athlete_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession([run(athlete_id, now - timedelta(days=2), 3.5, 31)])
    recommended = save_goal(
        db,
        athlete_id,
        goal_type="consistency",
        phase="maintenance",
        target_date=None,
        now=now,
    )
    plan_id = uuid.UUID(recommended["plan"]["id"])
    original = dict(recommended["plan"])

    moved = apply_plan_action(
        db,
        athlete_id,
        plan_id,
        action="move",
        payload={"scheduled_for": "2026-09-20"},
        now=now,
    )

    assert moved["plan"]["status"] == "adjusted"
    assert moved["plan"]["scheduled_for"] == "2026-09-20"
    assert moved["plan"]["duration_minutes"] == original["duration_minutes"]
    assert moved["plan"]["distance_miles"] == original["distance_miles"]
    assert moved["plan"]["effort_range"] == original["effort_range"]


def test_matched_completion_requires_current_owned_safe_candidate():
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    db = FakeSession([run(athlete_id, now - timedelta(days=2), 3.5, 31)])
    recommended = save_goal(
        db,
        athlete_id,
        goal_type="consistency",
        phase="maintenance",
        target_date=None,
        now=now,
    )
    plan_id = uuid.UUID(recommended["plan"]["id"])
    apply_plan_action(db, athlete_id, plan_id, action="accept", payload={}, now=now)

    foreign = run(other_id, datetime(2026, 9, 18, 17, tzinfo=timezone.utc), 2.5, 25)
    db.add(foreign)
    with pytest.raises(HTTPException) as exc_info:
        apply_plan_action(
            db,
            athlete_id,
            plan_id,
            action="complete",
            payload={
                "perceived_effort": "as_expected",
                "matched_activity_id": str(foreign.id),
            },
            now=now,
        )
    assert exc_info.value.status_code == 422

    owned = run(athlete_id, datetime(2026, 9, 18, 18, tzinfo=timezone.utc), 2.5, 25)
    db.add(owned)
    completed = apply_plan_action(
        db,
        athlete_id,
        plan_id,
        action="complete",
        payload={
            "perceived_effort": "as_expected",
            "note": "Matched the saved decision.",
            "matched_activity_id": str(owned.id),
        },
        now=now,
    )
    assert completed["plan"]["feedback"]["completion_source"] == "canonical_match"
    assert completed["plan"]["feedback"]["matched_activity_id"] == str(owned.id)
