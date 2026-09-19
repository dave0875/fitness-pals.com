"""Tests for the welcome/onboarding backend surface."""

from __future__ import annotations

import json
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
        if hasattr(side, "value"):
            return side.value
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


def _garmin_token(user_id):
    return UserProviderToken(
        user_id=user_id,
        tenant_id=None,
        provider="garmin",
        access_token_encrypted=b"x",
        refresh_token_encrypted=b"y",
        scope="activity",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        provider_user_id="garmin-user",
        metadata_json={},
    )


def _sync_job(user_id, status="queued", goal="marathon"):
    return SyncJob(
        user_id=user_id,
        provider="garmin",
        status=status,
        trigger="manual",
        test_run=False,
        payload_json={"goal": goal},
    )


def test_onboarding_status_requires_garmin_connection():
    """Users without Garmin should be prompted to connect Garmin."""
    user = _fake_user()
    db = FakeSession()

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["garmin_connected"] is False
    assert result["first_sync"]["state"] == "not_started"
    assert result["latest_activities"] == []
    assert result["training_volume_preview"] is None
    assert result["coach_insight"] is None
    assert result["next_action"] is None


def test_scraper_onboarding_does_not_offer_unusable_browser_authorization(monkeypatch):
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    result = onboarding.status(
        request=SimpleNamespace(cookies={}), user=_fake_user(), db=FakeSession()
    )
    assert result["garmin_authorization_available"] is False


def test_official_grant_is_not_misreported_as_import_ready(monkeypatch):
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    user = _fake_user()
    token = _garmin_token(user.id)
    token.metadata_json = {"auth_scheme": "garmin_official_oauth2"}
    db = FakeSession([token])
    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)
    assert result["garmin_connected"] is True
    assert result["garmin_sync_available"] is False
    with pytest.raises(HTTPException) as exc:
        onboarding.first_sync(
            onboarding.FirstSyncRequest(goal="marathon"), Response(), user, db
        )
    assert exc.value.status_code == 503


def test_onboarding_status_requires_reconnect_after_garmin_grant_expires(monkeypatch):
    """An expired 30-day grant returns the athlete to Garmin sign-in."""
    user = _fake_user()
    token = _garmin_token(user.id)
    token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: token,
    )

    result = onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=FakeSession([token]),
    )

    assert result["garmin_connected"] is False
    assert result["first_sync"]["state"] == "not_started"


def test_archive_data_completes_onboarding_without_live_garmin_connection(monkeypatch):
    """Archive-only athletes can reach first value without granting live access."""
    user = _fake_user()
    activity = _activity(user.id, 1, 12000.0)
    activity.start_time = datetime.now(timezone.utc) - timedelta(days=1)
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: None)

    result = onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=FakeSession([activity]),
    )

    assert result["garmin_connected"] is False
    assert result["first_sync"]["state"] == "completed"
    assert len(result["latest_activities"]) == 1
    assert result["training_volume_preview"] is not None


def test_onboarding_status_returns_sync_queued_with_selected_goal(monkeypatch):
    """Queued first-sync work should expose selected goal and queued state."""
    user = _fake_user()
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    job = _sync_job(user.id, status="queued", goal="half")
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(onboarding, "_latest_activities", lambda *_args, **_kwargs: [])
    db = FakeSession([_garmin_token(user.id), job])

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["garmin_connected"] is True
    assert result["first_sync"]["state"] == "queued"
    assert result["selected_goal"] == "half"



@pytest.mark.parametrize(
    ("error_payload", "expected_state", "expected_category"),
    [
        (
            {
                "status_code": 401,
                "message": "authorization failed for secret-token",
            },
            "authorization_required",
            "authorization",
        ),
        (
            {
                "type": "TimeoutError",
                "message": "upstream timed out after sending secret-token",
            },
            "failed",
            "upstream",
        ),
    ],
)
def test_onboarding_status_redacts_failed_sync_details(
    monkeypatch, error_payload, expected_state, expected_category
):
    """Failed syncs expose a recovery category without leaking provider details."""
    user = _fake_user()
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    job = _sync_job(user.id, status="failed")
    job.error_json = error_payload
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(onboarding, "_latest_activities", lambda *_args, **_kwargs: [])

    result = onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=FakeSession([_garmin_token(user.id), job]),
    )

    assert result["first_sync"]["state"] == expected_state
    assert result["first_sync"]["failure_category"] == expected_category
    assert "secret-token" not in json.dumps(result)


def test_onboarding_status_reports_partial_completed_sync(monkeypatch):
    """A completed sync with no canonical activities is honest about partial data."""
    user = _fake_user()
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    job = _sync_job(user.id, status="completed")
    job.finished_at = datetime.now(timezone.utc)
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(onboarding, "_latest_activities", lambda *_args, **_kwargs: [])

    result = onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=FakeSession([_garmin_token(user.id), job]),
    )

    assert result["first_sync"]["state"] == "partial"
    assert result["first_sync"]["retryable"] is True


def test_onboarding_status_reports_stale_completed_sync(monkeypatch):
    """A completed sync older than the product freshness window requests refresh."""
    user = _fake_user()
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    job = _sync_job(user.id, status="completed")
    job.finished_at = datetime.now(timezone.utc) - timedelta(hours=73)
    activity = _activity(user.id, 1, 12000.0)
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
        ],
    )

    result = onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=FakeSession([_garmin_token(user.id), job, activity]),
    )

    assert result["first_sync"]["state"] == "stale"
    assert result["first_sync"]["retryable"] is True

def test_onboarding_status_returns_first_win_preview_when_synced(monkeypatch):
    """Completed sync with canonical activity data should expose first-win preview."""
    user = _fake_user()
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    job = _sync_job(user.id, status="completed", goal="marathon")
    activities = [_activity(user.id, 1, 12000.0), _activity(user.id, 3, 8000.0)]
    for activity in activities:
        activity.start_time = datetime.now(timezone.utc) - timedelta(days=1)
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
            _garmin_token(user.id),
            job,
            *activities,
        ]
    )

    result = onboarding.status(request=SimpleNamespace(cookies={}), user=user, db=db)

    assert result["first_sync"]["state"] == "completed"
    assert result["selected_goal"] == "marathon"
    assert len(result["latest_activities"]) == 2
    assert result["training_volume_preview"]["summary"]
    assert result["coach_insight"]["title"]
    assert result["coach_insight"]["explanation"]
    assert result["next_action"]["label"]
    assert result["next_action"]["href"] == "/dashboard"


def test_first_sync_persists_goal_in_sync_job_payload(monkeypatch):
    """Queueing first sync should persist the selected goal into the sync job payload."""
    user = _fake_user()
    captured = {}
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )

    def fake_enqueue(db, user, goal):  # pylint: disable=unused-argument,redefined-outer-name
        captured["user_id"] = user.id
        captured["goal"] = goal
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(onboarding, "_enqueue_garmin_sync_job", fake_enqueue)

    result = onboarding.first_sync(
        body=onboarding.FirstSyncRequest(goal="recovery"),
        response=Response(),
        user=user,
        db=FakeSession([_garmin_token(user.id)]),
    )

    assert result["state"] == "queued"
    assert captured["user_id"] == user.id
    assert captured["goal"] == "recovery"

def test_first_sync_requires_garmin_connection():
    """First sync cannot be queued until the current user has a Garmin grant."""
    user = _fake_user()

    with pytest.raises(HTTPException) as exc_info:
        onboarding.first_sync(
            body=onboarding.FirstSyncRequest(goal="consistency"),
            response=Response(),
            user=user,
            db=FakeSession(),
        )

    assert exc_info.value.status_code == 409
    assert "Garmin" in str(exc_info.value.detail)


def test_first_sync_reuses_inflight_garmin_job(monkeypatch):
    """Repeated first-sync requests do not enqueue duplicate Garmin work."""
    user = _fake_user()
    job = _sync_job(user.id, status="running", goal="half")
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: _garmin_token(user.id),
    )
    monkeypatch.setattr(onboarding, "_latest_sync_job", lambda *_args, **_kwargs: job)

    def fail_enqueue(*_args, **_kwargs):
        raise AssertionError("in-flight first sync must be reused")

    monkeypatch.setattr(onboarding, "_enqueue_garmin_sync_job", fail_enqueue)

    result = onboarding.first_sync(
        body=onboarding.FirstSyncRequest(goal="half"),
        response=Response(),
        user=user,
        db=FakeSession([_garmin_token(user.id), job]),
    )

    assert result["state"] == "running"
    assert result["sync_job_id"] == str(job.id)
    assert result["reused"] is True
