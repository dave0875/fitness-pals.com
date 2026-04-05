"""Unit tests for Garmin batch scheduling behavior."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

from app.models import UserProviderToken
from app.services import garmin_scheduler


class FakeSession:
    """Minimal SQLAlchemy-like session stub for scheduler tests."""

    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for provider-token filtering."""

    def __init__(self, data):
        self.data = data

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def all(self):
        return list(self.data)

    @staticmethod
    def _resolve_value(side, item):
        if isinstance(side, BindParameter):
            return side.value
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        return side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            if condition.operator is operators.and_:
                return all(self._matches(c, item) for c in condition.clauses)
            if condition.operator is operators.or_:
                return any(self._matches(c, item) for c in condition.clauses)
        if isinstance(condition, BinaryExpression):
            left = self._resolve_value(condition.left, item)
            right = self._resolve_value(condition.right, item)
            return condition.operator(left, right)
        return True


def test_fetch_all_uses_scraper_tokens_in_scraper_mode(monkeypatch):
    """Batch scheduler should queue jobs without executing inline ingest."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    scraper_user_id = uuid.uuid4()
    tokens = [
        UserProviderToken(
            user_id=scraper_user_id,
            provider="garmin_scraper",
            access_token_encrypted=b"token",
        )
    ]
    db = FakeSession(tokens)
    calls = []

    def fake_enqueue_sync_job(db_arg, user_id, provider, trigger, **_kwargs):
        calls.append((db_arg, user_id, provider, trigger))
        return SimpleNamespace(id=uuid.uuid4(), status="queued")

    monkeypatch.setattr(garmin_scheduler, "enqueue_sync_job", fake_enqueue_sync_job)

    result = garmin_scheduler.fetch_all(db)

    assert result == {"status": "queued", "queued": 1, "errors": 0}
    assert calls == [(db, scraper_user_id, "garmin", "scheduler")]
