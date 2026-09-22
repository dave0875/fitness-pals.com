"""Behavior tests for Product V2 durable Coach threads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.llm.client import CoachUnavailableError
from app.models import Activity, AthleteGoal, Conversation, NextSessionPlan
from app.routes.chat import (
    ChatRequest,
    CoachContext,
    chat,
    clear_thread_context,
    get_thread,
    list_threads,
)


class FakeQuery:
    """Small SQLAlchemy-like query facade for Coach contract tests."""

    def __init__(self, data):
        self.data = list(data)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(condition, item) for condition in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def all(self):
        return list(self.data)

    def first(self):
        return self.data[0] if self.data else None

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        return FakeQuery(self.data[:count])

    @staticmethod
    def _resolve(side, item):
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        if hasattr(side, "value"):
            return side.value
        return side

    def _matches(self, condition, item):
        left = self._resolve(getattr(condition, "left", None), item)
        right = self._resolve(getattr(condition, "right", None), item)
        operator = getattr(condition, "operator", None)
        if operator is None:
            return True
        try:
            return operator(left, right)
        except Exception:
            return True


class FakeSession:
    """Persistence facade that keeps created rows available to later requests."""

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


def activity(user_id, days_ago=1):
    return Activity(
        id=uuid4(),
        user_id=user_id,
        start_time=datetime.now(timezone.utc) - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=10000.0,
        sport="run",
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}",
        metadata_json={"name": "Long progression run"},
    )


def goal_and_plan(user_id):
    goal = AthleteGoal(
        id=uuid4(),
        user_id=user_id,
        goal_type="marathon",
        phase="build",
        target_date=datetime(2026, 11, 1).date(),
    )
    plan = NextSessionPlan(
        id=uuid4(),
        user_id=user_id,
        goal_id=goal.id,
        status="recommended",
        session_purpose="Aerobic durability",
        scheduled_for=datetime(2026, 9, 23).date(),
        recommendation_json={
            "duration_minutes": {"min": 45, "max": 55},
            "distance_miles": None,
            "effort_range": "Easy and conversational",
        },
        rationale_json={"evidence": [], "rationale": [], "uncertainty": []},
    )
    return goal, plan


def test_followup_persists_thread_context_history_and_evidence():
    user_id = uuid4()
    user = SimpleNamespace(id=user_id)
    run = activity(user_id)
    goal, plan = goal_and_plan(user_id)
    db = FakeSession([run, goal, plan])
    captured = []

    def answer(message, metrics):
        captured.append((message, metrics))
        return f"answer-{len(captured)}"

    with patch("app.routes.chat.run_coach_prompt", side_effect=answer):
        first = chat(
            ChatRequest(
                message="How did this help my goal?",
                context=CoachContext(
                    source_route=f"/activities/{run.id}",
                    activity_id=run.id,
                    label="Long progression run",
                ),
            ),
            user=user,
            db=db,
        )
        second = chat(
            ChatRequest(
                message="Why?",
                thread_id=UUID(first["thread"]["id"]),
            ),
            user=user,
            db=db,
        )

    assert first["turn"]["status"] == "success"
    assert second["thread"]["id"] == first["thread"]["id"]
    assert len(second["thread"]["turns"]) == 2
    assert captured[1][1]["conversation_history"] == [
        {"question": "How did this help my goal?", "answer": "answer-1"}
    ]
    attached = captured[1][1]["coach_context"]["activity"]
    assert attached["id"] == str(run.id)
    assert attached["href"] == f"/activities/{run.id}"
    assert any(item["kind"] == "measured" for item in second["turn"]["evidence"])
    assert any(item["kind"] == "derived" for item in second["turn"]["evidence"])
    assert any(
        action["id"] == "accept-plan" for action in second["thread"]["actions"]
    )


def test_thread_reads_are_athlete_isolated_even_when_thread_id_is_known():
    owner_id = uuid4()
    other_id = uuid4()
    thread_id = uuid4()
    db = FakeSession(
        [
            Conversation(
                id=uuid4(),
                user_id=other_id,
                question="private question",
                answer="private answer",
                metadata_json={"thread_id": str(thread_id), "status": "success"},
                created_at=datetime.now(timezone.utc),
            )
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        get_thread(thread_id, user=SimpleNamespace(id=owner_id), db=db)

    assert exc_info.value.status_code == 404
    assert list_threads(user=SimpleNamespace(id=owner_id), db=db)["threads"] == []


def test_failed_model_turn_is_saved_and_retry_updates_same_turn():
    user_id = uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession([activity(user_id)])

    with patch(
        "app.routes.chat.run_coach_prompt",
        side_effect=CoachUnavailableError("temporary"),
    ):
        failed = chat(ChatRequest(message="What changed?"), user=user, db=db)

    assert failed["turn"]["status"] == "failed"
    assert failed["turn"]["retryable"] is True
    rows = [item for item in db.items if isinstance(item, Conversation)]
    assert len(rows) == 1

    with patch("app.routes.chat.run_coach_prompt", return_value="Recovered answer"):
        recovered = chat(
            ChatRequest(
                thread_id=UUID(failed["thread"]["id"]),
                retry_turn_id=UUID(failed["turn"]["id"]),
            ),
            user=user,
            db=db,
        )

    assert recovered["turn"]["status"] == "success"
    assert recovered["turn"]["answer"] == "Recovered answer"
    assert len([item for item in db.items if isinstance(item, Conversation)]) == 1


def test_activity_context_must_belong_to_current_athlete():
    owner_id = uuid4()
    foreign = activity(uuid4())
    db = FakeSession([foreign])

    with pytest.raises(HTTPException) as exc_info:
        with patch("app.routes.chat.run_coach_prompt", return_value="must not run"):
            chat(
                ChatRequest(
                    message="Tell me about this",
                    context=CoachContext(activity_id=foreign.id),
                ),
                user=SimpleNamespace(id=owner_id),
                db=db,
            )

    assert exc_info.value.status_code == 404


def test_context_can_be_removed_without_deleting_thread():
    user_id = uuid4()
    user = SimpleNamespace(id=user_id)
    run = activity(user_id)
    db = FakeSession([run])

    with patch("app.routes.chat.run_coach_prompt", return_value="answer"):
        created = chat(
            ChatRequest(
                message="Review this",
                context=CoachContext(activity_id=run.id, label="Attached run"),
            ),
            user=user,
            db=db,
        )

    thread_id = UUID(created["thread"]["id"])
    cleared = clear_thread_context(thread_id, user=user, db=db)

    assert cleared["context"] is None
    assert len(cleared["turns"]) == 1
