"""Tests for the welcome/onboarding backend surface."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException, Response
import pytest

os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("GARMIN_MODE", "oauth")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_ID", "test-google-client")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_SECRET", "test-google-secret")
os.environ.setdefault(
    "RUNTRAINER_GOOGLE_REDIRECT_URI", "https://example.com/auth/google/callback"
)

from app.models import Activity, SyncJob, UserProviderToken
from app.routes import onboarding


class FakeQuery:
    """Very small query stub for onboarding route tests."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.items:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def order_by(self, *orderings):
        ordered = list(self.items)
        for ordering in reversed(orderings):
            attr = getattr(getattr(ordering, "element", None), "key", None) or getattr(ordering, "key", None)
            reverse = getattr(ordering, "modifier", None) is not None or "desc" in str(ordering).lower()
            if attr:
                ordered.sort(key=lambda item: getattr(item, attr, None), reverse=reverse)
        return FakeQuery(ordered)

    def limit(self, count):
        return FakeQuery(self.items[:count])

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None

    @staticmethod
    def _resolve(side, item):
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        return side

    def _matches(self, condition, item):
        operator = getattr(condition, "operator", None)
        if operator is None:
            return True
        left = self._resolve(getattr(condition, "left", None), item)
        right = self._resolve(getattr(condition, "right", None), item)
        try:
            return operator(left, right)
        except Exception:
            return True


class FakeSession:
    """Simple session stub for onboarding tests."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.added = []

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def add(self, obj):
        self.items.append(obj)
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def _fake_user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=None)


def _activity(user_id, days_ago, distance_m, sport="run"):
    return Activity(
        user_id=user_id,
        start_time=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc) - timedelta(days=days_ago),
        duration_seconds=3600,
        distance_m=distance_m,
        sport=sport,
        status="merged",
        fingerprint_hash=f"fp-{user_id}-{days_ago}-{distance_m}",
        metadata_json={},
    )


def _pulsai_token(user_id):
    return UserProviderToken(
        user_id=user_id,
        tenant_id=None,
        provider="pulsai",
        access_token_encrypted=b"x",
        refresh_token_encrypted=b"y",
        scope="activity",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        provider_user_id="pulsai-user",
        metadata_json={},
    )


def _sync_job(user_id, status="queued", goal="marathon"):
    return SyncJob(
        user_id=user_id,
        provider="pulsai",
        status=status,
        trigger="manual",
        test_run=False,
        payload_json={"goal": goal},
    )


def test_onboarding_status_requires_pulsai_connection():
    """Users without PulsAI should be prompted to connect PulsAI."""
    user = _fake_user()
    db = FakeSession()

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["pulsai_connected"] is False
    assert result["first_sync"]["state"] == "not_started"
    assert result["latest_activities"] == []
    assert result["readiness_preview"] is None
    assert result["coach_insight"] is None
    assert result["next_action"] is None


def test_onboarding_status_returns_sync_queued_with_selected_goal(monkeypatch):
    """Queued first-sync work should expose selected goal and queued state."""
    user = _fake_user()
    job = _sync_job(user.id, status="queued", goal="half")
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(onboarding, "_latest_activities", lambda *_args, **_kwargs: [])
    db = FakeSession([_pulsai_token(user.id), job])

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["pulsai_connected"] is True
    assert result["first_sync"]["state"] == "queued"
    assert result["selected_goal"] == "half"


def test_onboarding_status_returns_first_win_preview_when_synced(monkeypatch):
    """Completed sync with canonical activity data should expose first-win preview."""
    user = _fake_user()
    job = _sync_job(user.id, status="completed", goal="marathon")
    activities = [_activity(user.id, 1, 12000.0), _activity(user.id, 3, 8000.0)]
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(
        onboarding,
        "_latest_activities",
        lambda *_args, **_kwargs: [
            {
                "id": str(activity.id),
                "sport": activity.sport,
                "start_time": activity.start_time.isoformat(),
                "distance_m": float(activity.distance_m or 0),
                "duration_seconds": activity.duration_seconds,
            }
            for activity in activities
        ],
    )
    db = FakeSession(
        [
            _pulsai_token(user.id),
            job,
            *activities,
        ]
    )

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["first_sync"]["state"] == "completed"
    assert result["selected_goal"] == "marathon"
    assert len(result["latest_activities"]) == 2
    assert result["readiness_preview"]["summary"]
    assert result["coach_insight"]["title"]
    assert result["coach_insight"]["explanation"]
    assert result["next_action"]["label"]
    assert result["next_action"]["href"] == "/dashboard"


def test_first_sync_persists_goal_in_sync_job_payload(monkeypatch):
    """Queueing first sync should persist the selected goal into the sync job payload."""
    user = _fake_user()
    captured = {}

    def fake_enqueue(db, user, goal):  # pylint: disable=unused-argument,redefined-outer-name
        captured["user_id"] = user.id
        captured["goal"] = goal
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(onboarding, "_enqueue_pulsai_sync_job", fake_enqueue)

    result = onboarding.first_sync(
        body=onboarding.FirstSyncRequest(goal="recovery"),
        response=Response(),
        user=user,
        db=FakeSession([_pulsai_token(user.id)]),
    )

    assert result["state"] == "queued"
    assert captured["user_id"] == user.id
    assert captured["goal"] == "recovery"

def test_first_sync_requires_pulsai_connection():
    """First sync cannot be queued until the current user has a PulsAI endpoint."""
    user = _fake_user()

    with pytest.raises(HTTPException) as exc_info:
        onboarding.first_sync(
            body=onboarding.FirstSyncRequest(goal="consistency"),
            response=Response(),
            user=user,
            db=FakeSession(),
        )

    assert exc_info.value.status_code == 409
    assert "PulsAI" in str(exc_info.value.detail)
