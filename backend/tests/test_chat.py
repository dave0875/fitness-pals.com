"""Tests for the chat endpoint that proxies metrics + LLM calls."""

from unittest.mock import patch

from app.models import User
from app.routes.chat import ChatRequest, chat


class DummySession:
    """Minimal session stub."""

    def add(self, _obj):
        """No-op add."""

    def commit(self):
        """No-op commit."""


def test_chat_endpoint():
    """Chat route should merge metrics and LLM response."""
    user = User(id=None, email="x@example.com")
    db = DummySession()
    with patch("app.routes.chat.summary", return_value={"mileage": {}}), patch(
        "app.routes.chat.run_coach_prompt", return_value="hi"
    ):
        resp = chat(ChatRequest(message="hello"), user=user, db=db)
        assert resp["response"] == "hi"
