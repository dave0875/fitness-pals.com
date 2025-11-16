from unittest.mock import patch

from app.routes.chat import chat, ChatRequest
from app.models import User


class DummySession:
    def add(self, obj): ...
    def commit(self): ...


def test_chat_endpoint():
    user = User(id=None, email="x@example.com")
    db = DummySession()
    with patch("app.routes.chat.summary", return_value={"mileage": {}}), patch(
        "app.routes.chat.run_coach_prompt", return_value="hi"
    ):
        resp = chat(ChatRequest(message="hello"), user=user, db=db)
        assert resp["response"] == "hi"
