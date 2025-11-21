"""Tests for Garmin OAuth login and callback flows."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import requests_mock
from fastapi import HTTPException

from app.routes import providers_garmin
from app.services.providers import ProviderTokenDetails, save_user_provider_token


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class FakeSession:
    """Minimal session stub to test saving tokens in callback."""

    def __init__(self):
        self.items = []

    def query(self, _model):
        return FakeQuery(self.items)

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def test_login_builds_redirect(monkeypatch):
    """Login endpoint should build a Garmin auth URL with configured env."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    resp = providers_garmin.garmin_login(SimpleNamespace())
    assert resp.status_code in (302, 307)
    assert "response_type=code" in resp.headers["location"]
    assert "client_id=cid" in resp.headers["location"]
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in resp.headers["location"]


def test_callback_happy_path(monkeypatch):
    """Callback should exchange code and store encrypted tokens."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    with requests_mock.Mocker() as m:
        m.post(
            providers_garmin.GARMIN_TOKEN_URL,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "activity",
                "user_id": "garmin-user",
            },
            status_code=200,
        )
        result = providers_garmin.garmin_callback(code="abc", user=user, db=db)
    assert result["status"] == "connected"
    assert db.items, "Token should be saved"
    stored = db.items[0]
    assert stored.provider == "garmin"
    assert stored.access_token_encrypted != b"at"
    assert stored.refresh_token_encrypted != b"rt"
    assert stored.expires_at and isinstance(stored.expires_at, datetime)
    assert stored.tenant_id is None


def test_callback_missing_code(monkeypatch):
    """Callback should fail when no code is provided."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    with pytest.raises(HTTPException):
        providers_garmin.garmin_callback(code=None, user=SimpleNamespace(), db=FakeSession())
