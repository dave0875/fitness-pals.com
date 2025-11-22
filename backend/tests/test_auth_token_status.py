"""Tests for token status endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.routes import auth_status, providers_garmin
from app.models import UserProviderToken


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
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    token = FakeToken(expires_at=expires)

    def fake_get(db, user_id, provider, tenant_id):  # pylint: disable=unused-argument
        return token if provider == "garmin" else None

    monkeypatch.setattr(providers_garmin, "get_user_provider_token", fake_get)
    result = providers_garmin.garmin_token_status(
        user=SimpleNamespace(id=uuid.uuid4(), tenant_id=None),
        db=None,
    )
    assert result["status"] == "active"
    assert result["refresh_token_present"] is True
    assert result["seconds_remaining"] > 0


def test_get_current_user_autocreates_on_google(monkeypatch):
    from app import deps  # imported here to avoid circular import at module load

    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    deps.settings.google_client_id = "test-google-client"

    def fake_verify(token, request_obj, audience):  # pylint: disable=unused-argument
        assert token == "token"
        assert audience == "test-google-client"
        return {"email": "new@example.com", "name": "New User", "picture": "http://img", "exp": future.timestamp()}

    class FakeSession:
        def __init__(self):
            self.added = None

        def query(self, model):  # pylint: disable=unused-argument
            return self

        def filter(self, condition):  # pylint: disable=unused-argument
            return self

        def first(self):
            return None

        def add(self, obj):
            self.added = obj

        def commit(self):
            return None

        def refresh(self, obj):  # pylint: disable=unused-argument
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(deps.google_id_token, "verify_oauth2_token", fake_verify)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    session = FakeSession()

    user = deps.get_current_user(credentials=creds, db=session)
    assert session.added is user
    assert user.email == "new@example.com"
