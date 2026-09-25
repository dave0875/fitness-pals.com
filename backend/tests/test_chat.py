"""Tests for the chat endpoint that proxies metrics + LLM calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Activity, AthleteGoal, Conversation, NextSessionPlan
from app.routes.chat import ChatRequest, chat


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for canonical read-model tests."""

    def __init__(self, data):
        self.data = list(data)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def all(self):
        return list(self.data)

    def first(self):
        return self.data[0] if self.data else None

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    @staticmethod
    def _resolve_value(side, item):
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        if hasattr(side, "value"):
            return side.value
        return side

    def _matches(self, condition, item):
        left = self._resolve_value(getattr(condition, "left", None), item)
        right = self._resolve_value(getattr(condition, "right", None), item)
        operator = getattr(condition, "operator", None)
        if operator is None:
            return True
        try:
            return operator(left, right)
        except Exception:
            return True


class FakeSession:
    """Minimal session stub that can hold canonical rows and persisted conversations."""

    def __init__(self, items):
        self.items = list(items)
        self.added = []

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def add(self, obj):
        self.added.append(obj)
        self.items.append(obj)

    def commit(self):
        return None


def _make_activity(user_id, days_ago, distance_m):
    return Activity(
        user_id=user_id,
        start_time=datetime.now(timezone.utc) - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport="run",
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}-{distance_m}",
        metadata_json={},
    )


def test_chat_assembles_context_from_canonical_read_model():
    """Chat should receive and persist canonical values plus freshness metadata."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [
            _make_activity(user_id, 2, 6000.0),
            _make_activity(user_id, 11, 12000.0),
        ]
    )
    captured = {}

    def fake_run_coach_prompt(message, metrics):
        captured["message"] = message
        captured["metrics"] = metrics
        return "coach-response"

    with patch("app.routes.chat.run_coach_prompt", side_effect=fake_run_coach_prompt):
        resp = chat(ChatRequest(message="what should I do?"), user=user, db=db)

    assert resp["response"] == "coach-response"
    assert captured["message"] == "what should I do?"
    assert captured["metrics"]["source"] == "canonical_postgres"
    assert captured["metrics"]["state"] == "fresh"
    assert captured["metrics"]["generated_at"]
    assert captured["metrics"]["data_through"]
    assert captured["metrics"]["mileage"]["30d"] == 18000.0
    assert captured["metrics"]["long_run_max"] == 12000.0
    assert captured["metrics"]["training_load"] is None
    assert captured["metrics"]["decision"]["source"] == "canonical_postgres"
    assert captured["metrics"]["decision"]["action"]["code"] == "set_goal"
    stored_conversation = next(
        item for item in db.added if isinstance(item, Conversation)
    )
    assert stored_conversation.metadata_json["metrics"]["mileage"]["30d"] == 18000.0
    assert stored_conversation.metadata_json["metrics"]["state"] == "fresh"
    assert stored_conversation.metadata_json["metrics"]["data_through"]
    assert stored_conversation.metadata_json["metrics"]["decision"] == captured["metrics"]["decision"]


def test_chat_receives_persisted_goal_phase_and_current_plan_context():
    """Coach chat should share the ongoing decision context, not only aggregates."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    goal = AthleteGoal(
        id=uuid.uuid4(),
        user_id=user_id,
        goal_type="marathon",
        phase="recovery",
        target_date=datetime(2026, 8, 22).date(),
    )
    plan = NextSessionPlan(
        id=uuid.uuid4(),
        user_id=user_id,
        goal_id=goal.id,
        status="accepted",
        session_purpose="Recovery movement",
        scheduled_for=datetime(2026, 9, 19).date(),
        recommendation_json={
            "duration_minutes": {"min": 20, "max": 25},
            "distance_miles": None,
            "effort_range": "Easy and conversational",
        },
        rationale_json={"evidence": [], "rationale": [], "uncertainty": []},
    )
    db = FakeSession([_make_activity(user_id, 2, 6000.0), goal, plan])
    captured = {}

    def fake_run_coach_prompt(message, metrics):
        captured.update(metrics)
        return "coach-response"

    with patch("app.routes.chat.run_coach_prompt", side_effect=fake_run_coach_prompt):
        chat(ChatRequest(message="Can I move this session?"), user=user, db=db)

    assert captured["today_plan"]["goal"]["phase"] == "recovery"
    assert captured["today_plan"]["plan"]["status"] == "accepted"
    assert captured["today_plan"]["plan"]["session_purpose"] == "Recovery movement"


def test_chat_never_passes_strength_sentinel_to_coach():
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    sentinel = _make_activity(user_id, 1, 21474836)
    sentinel.sport = "strength_training"
    db = FakeSession([sentinel])
    captured = {}
    with patch("app.routes.chat.run_coach_prompt", side_effect=lambda _message, metrics: captured.update(metrics) or "safe"):
        chat(ChatRequest(message="How far was my run?"), user=user, db=db)
    assert captured["long_run_max"] is None
    assert captured["mileage"]["30d"] is None
