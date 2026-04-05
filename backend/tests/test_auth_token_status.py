"""Tests for token status endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.routes import auth_status, providers_garmin
from app.models import UserProviderToken
from app.utils.security import APP_SESSION_COOKIE, create_access_token


@pytest.fixture
def google_token(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    auth_status.settings.google_client_id = "test-google-client"

    def fake_verify(token, request_obj, audience):  # pylint: disable=unused-argument
        assert token == "token"
        assert audience == "test-google-client"
        return {"email": "user@example.com", "exp": future.timestamp()}

    monkeypatch.setattr(auth_status.google_id_token, "verify_oauth2_token", fake_verify)
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def test_google_token_status_returns_email_and_expiry(google_token):
    result = auth_status.google_token_status(credentials=google_token)
    assert result["status"] == "active"
    assert result["user_email"] == "user@example.com"
    assert "expires_at" in result
    assert result["seconds_remaining"] > 0


class FakeToken(UserProviderToken):
    def __init__(self, expires_at, refresh=True):
        self.expires_at = expires_at
        self.refresh_token_encrypted = b"rt" if refresh else None
        self.provider_user_id = uuid.uuid4()
        self.metadata_json = {}


def test_garmin_token_status_missing(monkeypatch):
    monkeypatch.setattr(
        providers_garmin,
        "get_user_provider_token",
        lambda db, user_id, provider, tenant_id: None,
    )
    result = providers_garmin.garmin_token_status(
        user=SimpleNamespace(id=uuid.uuid4(), tenant_id=None),
        db=None,
    )
    assert result["status"] == "missing"


def test_garmin_token_status_active(monkeypatch):
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    token = FakeToken(expires_at=expires)
    calls = []

    def fake_get(db, user_id, provider, tenant_id):  # pylint: disable=unused-argument
        calls.append(provider)
        return token if provider == "garmin" else None

    monkeypatch.setattr(providers_garmin, "get_user_provider_token", fake_get)
    result = providers_garmin.garmin_token_status(
        user=SimpleNamespace(id=uuid.uuid4(), tenant_id=None),
        db=None,
        provider="garmin",
    )
    assert result["status"] == "active"
    assert result["provider"] == "garmin"
    assert result["mode"] == "oauth"
    assert result["refresh_token_present"] is True
    assert result["seconds_remaining"] > 0
    assert calls == ["garmin"]


def test_get_current_user_rejects_raw_google_token():
    from app import deps  # imported here to avoid circular import at module load

    class FakeSession:
        def query(self, model):  # pylint: disable=unused-argument
            return self

        def filter(self, condition):  # pylint: disable=unused-argument
            return self

        def first(self):
            return None

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(credentials=creds, db=FakeSession())

    assert exc_info.value.status_code == 401


def test_get_current_user_accepts_app_jwt():
    from app import deps  # imported here to avoid circular import at module load

    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    user = SimpleNamespace(id=user_id, email="new@example.com")

    class FakeSession:
        def query(self, model):  # pylint: disable=unused-argument
            return self

        def filter(self, condition):  # pylint: disable=unused-argument
            return self

        def first(self):
            return user

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert deps.get_current_user(credentials=creds, db=FakeSession()) is user


def test_get_current_user_accepts_app_session_cookie():
    from app import deps  # imported here to avoid circular import at module load

    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    user = SimpleNamespace(id=user_id, email="cookie@example.com")

    class FakeSession:
        def query(self, model):  # pylint: disable=unused-argument
            return self

        def filter(self, condition):  # pylint: disable=unused-argument
            return self

        def first(self):
            return user

    request = SimpleNamespace(cookies={APP_SESSION_COOKIE: token})
    assert deps.get_current_user(credentials=None, db=FakeSession(), request=request) is user
