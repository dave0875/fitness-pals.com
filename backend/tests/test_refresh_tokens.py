"""Refresh-session issuance, rotation, replay, revocation, and endpoint tests."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event
from sqlalchemy.orm import sessionmaker

from app import deps, main
from app.models import RefreshTokenSession, User
from app.services.refresh_tokens import (
    RefreshTokenRejected,
    issue_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.utils.security import (
    APP_REFRESH_COOKIE,
    APP_SESSION_COOKIE,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)


@pytest.fixture(scope="module")
def refresh_engine(tmp_path_factory):
    """Use the requested Postgres database or a thread-capable temporary SQLite file."""
    configured_url = os.environ.get("RUNTRAINER_REFRESH_TEST_DATABASE_URL")
    if configured_url:
        engine = create_engine(configured_url, pool_pre_ping=True, future=True)
    else:
        database = tmp_path_factory.mktemp("refresh-sessions") / "refresh.db"
        engine = create_engine(
            f"sqlite:///{database}",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
    User.__table__.create(engine, checkfirst=True)
    RefreshTokenSession.__table__.create(engine, checkfirst=True)
    yield engine
    if not configured_url:
        RefreshTokenSession.__table__.drop(engine, checkfirst=True)
        User.__table__.drop(engine, checkfirst=True)
    engine.dispose()


@pytest.fixture()
def refresh_db(refresh_engine):
    """Create an isolated athlete and clean all of its durable state afterward."""
    factory = sessionmaker(bind=refresh_engine, expire_on_commit=False, future=True)
    db = factory()
    user = User(email=f"refresh-{uuid.uuid4()}@example.com", name="Refresh Runner")
    db.add(user)
    db.commit()
    user_id = user.id
    try:
        yield db, user, factory
    finally:
        db.rollback()
        db.close()
        cleanup = factory()
        cleanup.execute(delete(RefreshTokenSession).where(RefreshTokenSession.user_id == user_id))
        cleanup.execute(delete(User).where(User.id == user_id))
        cleanup.commit()
        cleanup.close()


def test_issuance_persists_only_refresh_lifecycle_state(refresh_db):
    db, user, _factory = refresh_db
    pair = issue_token_pair(db, user.id)
    db.commit()

    session = db.get(RefreshTokenSession, pair.refresh_jti)
    assert session is not None
    assert session.user_id == user.id
    assert session.consumed_at is None
    assert session.revoked_at is None
    assert pair.refresh_token not in repr(session.as_dict())
    assert set(session.as_dict()) == {
        "jti", "user_id", "issued_at", "expires_at", "consumed_at", "revoked_at"
    }


def test_rotation_consumes_predecessor_persists_successor_and_rejects_replay(refresh_db):
    db, user, _factory = refresh_db
    original = issue_token_pair(db, user.id)
    db.commit()

    successor = rotate_refresh_token(db, original.refresh_token)

    predecessor = db.get(RefreshTokenSession, original.refresh_jti)
    persisted_successor = db.get(RefreshTokenSession, successor.refresh_jti)
    assert predecessor.consumed_at is not None
    assert persisted_successor is not None
    assert persisted_successor.consumed_at is None
    with pytest.raises(RefreshTokenRejected):
        rotate_refresh_token(db, original.refresh_token)


def test_unknown_and_revoked_refresh_sessions_fail_closed(refresh_db):
    db, user, _factory = refresh_db
    pair = issue_token_pair(db, user.id)
    db.commit()
    unknown = create_refresh_token(user.id)

    with pytest.raises(RefreshTokenRejected):
        rotate_refresh_token(db, unknown)
    assert revoke_refresh_token(db, pair.refresh_token) is True
    assert revoke_refresh_token(db, pair.refresh_token) is False
    with pytest.raises(RefreshTokenRejected):
        rotate_refresh_token(db, pair.refresh_token)


def test_successor_persistence_failure_rolls_back_predecessor_consumption(refresh_db):
    db, user, factory = refresh_db
    pair = issue_token_pair(db, user.id)
    db.commit()
    rotate_db = factory()

    def reject_successor(session, _flush_context, _instances):
        if any(isinstance(item, RefreshTokenSession) for item in session.new):
            raise RuntimeError("simulated successor persistence failure")

    event.listen(rotate_db, "before_flush", reject_successor)
    try:
        with pytest.raises(RuntimeError, match="successor persistence"):
            rotate_refresh_token(rotate_db, pair.refresh_token)
    finally:
        event.remove(rotate_db, "before_flush", reject_successor)
        rotate_db.close()

    db.expire_all()
    assert db.get(RefreshTokenSession, pair.refresh_jti).consumed_at is None


def test_concurrent_refresh_allows_exactly_one_rotation(refresh_db):
    db, user, factory = refresh_db
    pair = issue_token_pair(db, user.id)
    db.commit()
    barrier = threading.Barrier(2)
    outcomes = []
    outcome_lock = threading.Lock()

    def rotate_once():
        worker_db = factory()
        barrier.wait()
        try:
            rotate_refresh_token(worker_db, pair.refresh_token)
            outcome = "rotated"
        except RefreshTokenRejected:
            outcome = "rejected"
        finally:
            worker_db.close()
        with outcome_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=rotate_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["rejected", "rotated"]


def test_issuance_cleans_up_expired_refresh_state(refresh_db):
    db, user, _factory = refresh_db
    expired_jti = uuid.uuid4()
    db.add(
        RefreshTokenSession(
            jti=expired_jti,
            user_id=user.id,
            issued_at=datetime.now(timezone.utc) - timedelta(days=40),
            expires_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    db.commit()

    issue_token_pair(db, user.id)
    db.commit()

    assert db.get(RefreshTokenSession, expired_jti) is None


def _override_database(app, factory):
    def provide_db():
        request_db = factory()
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[deps.get_db] = provide_db


def _refresh_client(raw_token):
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(
        APP_REFRESH_COOKIE,
        raw_token,
        domain="testserver.local",
        path="/auth",
    )
    return client


def test_refresh_endpoint_rejects_malformed_expired_and_unknown_state_uniformly(refresh_db):
    db, user, factory = refresh_db
    expired = create_refresh_token(
        user.id,
        issued_at=datetime.now(timezone.utc) - timedelta(days=60),
    )
    unknown = create_refresh_token(user.id)
    _override_database(main.app, factory)
    try:
        for raw_token in ("not-a-jwt", expired, unknown):
            response = _refresh_client(raw_token).post("/auth/refresh")
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid refresh token"}
            assert "set-cookie" not in response.headers
    finally:
        main.app.dependency_overrides.clear()


def test_full_refresh_and_logout_lifecycle_invalidates_replayed_sessions(refresh_db):
    db, user, factory = refresh_db
    original = issue_token_pair(db, user.id)
    db.commit()
    _override_database(main.app, factory)
    client = _refresh_client(original.refresh_token)
    client.cookies.set(
        APP_SESSION_COOKIE,
        original.access_token,
        domain="testserver.local",
        path="/",
    )
    try:
        assert client.get("/api/auth/session").status_code == 200

        wrong_channel = _refresh_client(original.access_token).post("/auth/refresh")
        assert wrong_channel.status_code == 401

        client.cookies.set(
            APP_SESSION_COOKIE,
            create_access_token(
                user.id,
                issued_at=datetime.now(timezone.utc) - timedelta(days=1),
            ),
            domain="testserver.local",
            path="/",
        )
        assert client.get("/api/auth/session").status_code == 401

        refreshed = client.post("/auth/refresh")
        assert refreshed.status_code == 204
        set_cookies = refreshed.headers.get_list("set-cookie")
        assert any(
            f"{APP_REFRESH_COOKIE}=" in value
            and "Path=/auth" in value
            and "HttpOnly" in value
            and "Secure" in value
            and "SameSite=lax" in value
            for value in set_cookies
        )
        assert any(
            f"{APP_REFRESH_COOKIE}=" in value and "Path=/;" in value and "Max-Age=0" in value
            for value in set_cookies
        )
        assert client.get("/api/auth/session").status_code == 200

        replay = _refresh_client(original.refresh_token).post("/auth/refresh")
        assert replay.status_code == 401
        assert "set-cookie" not in replay.headers

        successor_token = client.cookies.get(APP_REFRESH_COOKIE)
        successor_jti = uuid.UUID(decode_refresh_token(successor_token)["jti"])
        assert client.post("/auth/refresh").status_code == 204

        active_token = client.cookies.get(APP_REFRESH_COOKIE)
        active_jti = uuid.UUID(decode_refresh_token(active_token)["jti"])
        logout = client.get("/auth/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert logout.headers["location"] == "/"
        clear_headers = logout.headers.get_list("set-cookie")
        refresh_clears = [value for value in clear_headers if f"{APP_REFRESH_COOKIE}=" in value]
        assert any("Path=/auth" in value and "Max-Age=0" in value for value in refresh_clears)
        assert any("Path=/;" in value and "Max-Age=0" in value for value in refresh_clears)

        db.expire_all()
        assert db.get(RefreshTokenSession, successor_jti).consumed_at is not None
        assert db.get(RefreshTokenSession, active_jti).revoked_at is not None
        assert _refresh_client(active_token).post("/auth/refresh").status_code == 401
    finally:
        main.app.dependency_overrides.clear()
