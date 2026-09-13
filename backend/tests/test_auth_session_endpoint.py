"""Tests for the lightweight auth session endpoint."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient


os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s=")
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_ID", "test-google-client")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_SECRET", "test-google-secret")
os.environ.setdefault("RUNTRAINER_GOOGLE_REDIRECT_URI", "https://example.com/auth/google/callback")

from app import deps, main  # noqa: E402  pylint: disable=wrong-import-position
from app.utils.security import (  # noqa: E402  pylint: disable=wrong-import-position
    APP_REFRESH_COOKIE,
    APP_SESSION_COOKIE,
    create_access_token,
    create_refresh_token,
)


class FakeQuery:
    """Minimal query stub for app-session lookup."""

    def __init__(self, user):
        self.user = user

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.user


class FakeSession:
    """Minimal DB session stub used by the session endpoint test."""

    def __init__(self, user):
        self.user = user

    def query(self, model):  # pylint: disable=unused-argument
        return FakeQuery(self.user)


def test_auth_session_endpoint_requires_login():
    """Anonymous requests should be rejected by the session endpoint."""
    client = TestClient(main.app)

    response = client.get("/api/auth/session")

    assert response.status_code == 401


def test_auth_session_endpoint_returns_app_session_for_cookie_user():
    """App-session cookies should resolve to an authenticated session response."""
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id, email="runner@example.com", name="Runner")
    token = create_access_token(user_id)

    client = TestClient(main.app)
    client.cookies.set(APP_SESSION_COOKIE, token)
    main.app.dependency_overrides[deps.get_db] = lambda: FakeSession(user)
    try:
        response = client.get("/api/auth/session")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user_id"] == str(user.id)
    assert body["email"] == "runner@example.com"
    assert body["session_type"] == "app"


def test_auth_session_endpoint_rejects_refresh_cookie_as_access_cookie():
    """A refresh JWT cannot be replayed through the access-cookie channel."""
    client = TestClient(main.app)
    client.cookies.set(APP_SESSION_COOKIE, create_refresh_token(uuid.uuid4()))

    response = client.get("/api/auth/session")

    assert response.status_code == 401


def test_logout_clears_app_cookies_and_returns_home():
    """Signing out should clear both app cookies and safely return home."""
    client = TestClient(main.app)
    client.cookies.set(APP_SESSION_COOKIE, "access-token")
    client.cookies.set(APP_REFRESH_COOKIE, "refresh-token")

    response = client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookies = response.headers.get_list("set-cookie")
    assert any(f"{APP_SESSION_COOKIE}=" in cookie and "Max-Age=0" in cookie for cookie in cookies)
    assert any(f"{APP_REFRESH_COOKIE}=" in cookie and "Max-Age=0" in cookie for cookie in cookies)
