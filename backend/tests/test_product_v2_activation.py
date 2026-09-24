"""Phase 2 Product V2 activation contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from fastapi import Response

from app.models import Activity, ArchiveImportJob, AthleteGoal, SyncJob, UserProviderToken
from app.routes import onboarding


class FakeQuery:
    """Small model-scoped query facade for activation tests."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *_criteria):
        return self

    def order_by(self, *_criteria):
        return self

    def limit(self, value):
        return FakeQuery(self.items[:value])

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None


class FakeSession:
    """In-memory persistence facade sufficient for activation contracts."""

    def __init__(self, items=()):
        self.items = list(items)

    def query(self, model):
        return FakeQuery(item for item in self.items if isinstance(item, model))

    def add(self, item):
        if item not in self.items:
            self.items.append(item)

    def commit(self):
        for item in self.items:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    def refresh(self, _item):
        return None


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=None, email="runner@example.com")


def _activity(user_id, *, days_ago=1):
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=datetime.now(timezone.utc) - timedelta(days=days_ago),
        duration_seconds=45 * 60,
        distance_m=8000.0,
        sport="run",
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={"name": "Run"},
    )


def _garmin_token(user_id, *, expired=False, official=False):
    return UserProviderToken(
        id=uuid.uuid4(),
        user_id=user_id,
        tenant_id=None,
        provider="garmin",
        access_token_encrypted=b"x",
        refresh_token_encrypted=b"y",
        scope="activity",
        expires_at=(
            datetime.now(timezone.utc) - timedelta(hours=1)
            if expired
            else datetime.now(timezone.utc) + timedelta(days=7)
        ),
        metadata_json={"auth_scheme": "garmin_official_oauth2"} if official else {},
    )


def _archive_job(user_id, status):
    return ArchiveImportJob(
        id=uuid.uuid4(),
        user_id=user_id,
        provider="garmin_archive",
        source_type="google_drive",
        source_locator="athlete-folder",
        status=status,
        filename="Garmin archive",
        content_type="application/vnd.google-apps.folder",
        size_bytes=0,
        storage_backend="google_drive",
        storage_key=f"google-drive/{user_id}/{uuid.uuid4()}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _sync_job(user_id, *, status="completed", days_ago=10):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return SyncJob(
        id=uuid.uuid4(),
        user_id=user_id,
        provider="garmin",
        status=status,
        trigger="manual",
        test_run=False,
        payload_json={"goal": "consistency"},
        created_at=when,
        updated_at=when,
        finished_at=when if status == "completed" else None,
    )


def _status(monkeypatch, user, db, token=None):
    monkeypatch.setattr(
        onboarding,
        "get_user_provider_token",
        lambda *_args, **_kwargs: token,
    )
    return onboarding.status(
        request=SimpleNamespace(cookies={}),
        user=user,
        db=db,
    )


def test_established_canonical_athlete_bypasses_activation_without_live_connection(monkeypatch):
    user = _user()
    result = _status(monkeypatch, user, FakeSession([_activity(user.id)]))

    assert result["activation"]["state"] == "fully_usable"
    assert result["activation"]["requires_activation"] is False
    assert result["activation"]["usable_now"] is True
    assert result["activation"]["resume_href"] == "/today"
    assert result["activation"]["coach_handoff"]["href"].startswith("/coach?")
    assert result["latest_activities"]


def test_active_archive_import_progresses_without_blocking_partial_value(monkeypatch):
    user = _user()
    processing = _archive_job(user.id, "processing")

    empty = _status(monkeypatch, user, FakeSession([processing]))
    assert empty["activation"]["state"] == "importing"
    assert empty["activation"]["requires_activation"] is True
    assert empty["activation"]["usable_now"] is False

    partial = _status(
        monkeypatch,
        user,
        FakeSession([processing, _activity(user.id)]),
    )
    assert partial["activation"]["state"] == "usable_partial"
    assert partial["activation"]["requires_activation"] is False
    assert partial["activation"]["usable_now"] is True


def test_activation_distinguishes_connected_stale_expired_failed_and_unsupported(monkeypatch):
    user = _user()

    connected = _status(
        monkeypatch,
        user,
        FakeSession(),
        token=_garmin_token(user.id),
    )
    assert connected["activation"]["state"] == "connected_no_data"

    stale = _status(
        monkeypatch,
        user,
        FakeSession([_activity(user.id, days_ago=5)]),
    )
    assert stale["activation"]["state"] == "stale"
    assert stale["activation"]["requires_activation"] is False

    expired = _status(
        monkeypatch,
        user,
        FakeSession(),
        token=_garmin_token(user.id, expired=True),
    )
    assert expired["activation"]["state"] == "authorization_expired"
    assert expired["activation"]["action"]["href"] == "/import/garmin-archive"

    failed = _status(
        monkeypatch,
        user,
        FakeSession([_archive_job(user.id, "failed")]),
    )
    assert failed["activation"]["state"] == "import_failed"
    assert failed["activation"]["action"]["href"] == "/import/garmin-archive"

    unsupported = _status(
        monkeypatch,
        user,
        FakeSession(),
        token=_garmin_token(user.id, official=True),
    )
    assert unsupported["activation"]["state"] == "unsupported_capability"
    assert unsupported["activation"]["action"]["enabled"] is True
    assert unsupported["activation"]["action"]["href"] == "/import/garmin-archive"


def test_fresh_canonical_evidence_wins_over_an_old_completed_sync_job(monkeypatch):
    user = _user()
    db = FakeSession([_sync_job(user.id, days_ago=10), _activity(user.id, days_ago=1)])

    result = _status(monkeypatch, user, db, token=_garmin_token(user.id))

    assert result["first_sync"]["state"] == "stale"
    assert result["activation"]["state"] == "fully_usable"
    assert result["activation"]["requires_activation"] is False


def test_goal_handshake_persists_rich_intent_in_durable_athlete_goal(monkeypatch):
    user = _user()
    db = FakeSession()
    monkeypatch.setattr(onboarding, "_set_goal_cookie", lambda *_args: None)

    result = onboarding.store_goal_handshake(
        body=onboarding.GoalHandshakeRequest(
            goal="other",
            phase="maintenance",
            target_date=None,
            target_distance="5K",
            target_performance="Finish feeling strong",
            target_time_seconds=1500,
            custom_goal="Run socially twice each week",
        ),
        response=Response(),
        user=user,
        db=db,
    )

    stored = next(item for item in db.items if isinstance(item, AthleteGoal))
    assert stored.goal_type == "other"
    assert stored.phase == "maintenance"
    assert stored.intent_json["target_distance"] == "5K"
    assert stored.intent_json["target_performance"] == "Finish feeling strong"
    assert stored.intent_json["target_time_seconds"] == 1500
    assert stored.intent_json["custom_goal"] == "Run socially twice each week"
    assert stored.intent_json["intent_source"] == "onboarding"
    assert result["intent"]["goal_type"] == "other"
    assert result["intent"]["target_time_seconds"] == 1500


def test_im_not_sure_is_a_valid_durable_intent(monkeypatch):
    user = _user()
    db = FakeSession()
    monkeypatch.setattr(onboarding, "_set_goal_cookie", lambda *_args: None)

    result = onboarding.store_goal_handshake(
        body=onboarding.GoalHandshakeRequest(goal="not_sure", phase="maintenance"),
        response=Response(),
        user=user,
        db=db,
    )

    assert result["intent"]["goal_type"] == "not_sure"
    assert result["intent"]["label"] == "I’m not sure"
