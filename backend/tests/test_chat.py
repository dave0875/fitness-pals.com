"""Tests for the chat endpoint that proxies metrics + LLM calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Activity, Conversation
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
    """Chat should still produce an LLM response when canonical data is available."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id)
    db = FakeSession(
        [
            _make_activity(user_id, 3, 6000.0),
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
    assert captured["metrics"]["mileage"]["30d"] == 18000.0
    assert captured["metrics"]["long_run_max"] == 12000.0
    assert captured["metrics"]["training_load"] == []
    stored_conversation = next(
        item for item in db.added if isinstance(item, Conversation)
    )
    assert stored_conversation.metadata_json["metrics"]["mileage"]["30d"] == 18000.0
