"""Tests for Garmin OAuth login and callback flows."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import requests_mock
from fastapi import HTTPException

from app.routes import providers_garmin
from app.models.provider import UserProviderToken
from app.services.providers import ProviderTokenDetails, save_user_provider_token


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class FakeSession:
    """Minimal session stub to test saving tokens in callback."""

    def __init__(self):
        self.items = []
        self.added_runs = []
        self.provider_tokens = []

    def query(self, _model):
        if getattr(_model, "__name__", "") == "UserProviderToken":
            return FakeQuery(self.provider_tokens)
        return FakeQuery(self.items)

    def add(self, obj):
        self.items.append(obj)
        self.added_runs.append(obj)
        if getattr(obj, "provider", None):
            self.provider_tokens.append(obj)

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
    token_url = providers_garmin._config()["token_url"]
    with requests_mock.Mocker() as m:
        m.post(
            token_url,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "activity",
                "user_id": "garmin-user",
            },
            status_code=200,
            headers={"content-type": "application/json"},
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


def test_refresh_happy_path(monkeypatch):
    """Refresh endpoint should rotate tokens when refresh token is present."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    # Seed existing token
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="old-at",
            refresh_token="old-rt",
        ),
    )
    token_url = providers_garmin._config()["token_url"]
    with requests_mock.Mocker() as m:
        m.post(
            token_url,
            json={"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 3600},
            status_code=200,
            headers={"content-type": "application/json"},
        )
        result = providers_garmin.garmin_refresh(user=user, db=db)
    assert result["status"] == "refreshed"
    stored = db.items[0]
    assert stored.refresh_token_encrypted != b"old-rt"


def test_refresh_reauth_when_missing_refresh(monkeypatch):
    """Refresh endpoint should require reauth when no refresh token stored."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="old-at",
            refresh_token=None,
        ),
    )
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_refresh(user=user, db=db)
    assert exc.value.status_code == 410


def test_fetch_all_batch(monkeypatch):
    """Batch fetch should continue across users and report runs/errors."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user1 = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    user2 = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user1.id,
            tenant_id=None,
            provider="garmin",
            access_token="at1",
            refresh_token="rt1",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
    )
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user2.id,
            tenant_id=None,
            provider="garmin",
            access_token="at2",
            refresh_token="rt2",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
    )
    with requests_mock.Mocker() as m:
        m.get("https://mock.garmin/activities", json=[{"id": 1}], status_code=200, headers={"content-type": "application/json"})
        summary = providers_garmin.garmin_fetch_all(SimpleNamespace(), db=db)
    assert summary["runs"] >= 1
    assert summary.get("errors", 0) >= 0


def test_refresh_reauth_on_failure(monkeypatch):
    """Refresh endpoint should require reauth when Garmin token refresh fails."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="old-at",
            refresh_token="old-rt",
        ),
    )
    token_url = providers_garmin._config()["token_url"]
    with requests_mock.Mocker() as m:
        m.post(token_url, status_code=400)
        with pytest.raises(HTTPException) as exc:
            providers_garmin.garmin_refresh(user=user, db=db)
    assert exc.value.status_code == 410


def test_fetch_happy_path(monkeypatch):
    """Fetch endpoint should ingest activities and return count."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="at",
            refresh_token="rt",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
    )
    with requests_mock.Mocker() as m:
        m.get("https://mock.garmin/activities", json=[{"id": 1}, {"id": 2}], status_code=200, headers={"content-type": "application/json"})
        resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "ok"
    assert resp["ingested"] == 2


def test_fetch_reauth_when_missing_token(monkeypatch):
    """Fetch should require reauth when no Garmin token stored."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410


def test_fetch_reauth_on_401(monkeypatch):
    """Fetch should require reauth when Garmin returns 401."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="at",
            refresh_token="rt",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ),
    )
    with requests_mock.Mocker() as m:
        m.get("https://mock.garmin/activities", status_code=401)
        with pytest.raises(HTTPException) as exc:
            providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410


def test_scraper_token_endpoint(monkeypatch):
    """Scraper token endpoint should store access token without credentials."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    req = providers_garmin.ScraperTokenRequest(scraper_access_token="scraper-at")
    resp = providers_garmin.garmin_scraper_token(body=req, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin_scraper"
    assert db.provider_tokens[0].refresh_token_encrypted is None


def test_scraper_fetch_happy_path(monkeypatch):
    """Scraper mode fetch should use stored scraper token and succeed."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="scraper-at",
        ),
    )
    with requests_mock.Mocker() as m:
        m.get("https://mock.garmin/activities", json=[{"id": 1}], status_code=200, headers={"content-type": "application/json"})
        resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "ok"
    assert resp["ingested"] == 1


def test_scraper_fetch_reauth_missing_token(monkeypatch):
    """Scraper mode should require reauth when no scraper token is stored."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410


def test_scraper_fetch_reauth_on_401(monkeypatch):
    """Scraper mode should require reauth when Garmin returns 401."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="scraper-at",
        ),
    )
    with requests_mock.Mocker() as m:
        m.get("https://mock.garmin/activities", status_code=401)
        with pytest.raises(HTTPException) as exc:
            providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410
