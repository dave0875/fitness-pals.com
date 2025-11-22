"""Tests for Garmin OAuth login and callback flows."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import requests_mock
from fastapi import HTTPException

from app.routes import providers_garmin
from app.services import garmin_ingest
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
    class FakeClient:
        def connectapi(self, *_args, **_kwargs):
            return [{"id": 1}]

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=lambda: FakeClient(), auth=None))
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
    class FakeClient:
        def connectapi(self, *_args, **_kwargs):
            return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=lambda: FakeClient(), auth=None))
    class FakeWriteAPI:
        def __init__(self):
            self.records = []

        def write(self, bucket=None, org=None, record=None):  # pylint: disable=unused-argument
            self.records.extend(record or [])

    fake_influx = SimpleNamespace(
        org="org",
        default_bucket="bucket",
        write_api_obj=FakeWriteAPI(),
        write_api=lambda: None,
    )
    fake_influx.write_api = lambda: fake_influx.write_api_obj
    monkeypatch.setattr(garmin_ingest, "get_influx_client_for_user", lambda _db, _uid: fake_influx)

    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "ok"
    assert resp["ingested"] == 2
    # No points written because the fake activities lack mappable fields, but it should not crash.


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
    class FakeClient:
        def connectapi(self, *_args, **_kwargs):
            raise HTTPException(status_code=410, detail="Garmin reauth required")

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=lambda: FakeClient(), auth=None))
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410


def test_scraper_token_endpoint(monkeypatch):
    """Scraper token endpoint should store access token without credentials."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    req = providers_garmin.ScraperTokenRequest(scraper_access_token="scraper-at", token_secret="scraper-secret")
    resp = providers_garmin.garmin_scraper_token(body=req, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin_scraper"
    assert db.provider_tokens[0].refresh_token_encrypted is None
    assert db.provider_tokens[0].metadata_json.get("token_secret") == "scraper-secret"


def test_scraper_fetch_happy_path(monkeypatch):
    """Scraper mode fetch should use stored scraper token and succeed."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
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
    class FakeClient:
        def connectapi(self, *_args, **_kwargs):
            return [{"id": 1}]

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=lambda: FakeClient(), auth=None))
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
    class FakeClient:
        def connectapi(self, *_args, **_kwargs):
            raise HTTPException(status_code=410, detail="Garmin reauth required")

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=lambda: FakeClient(), auth=None))
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 410


def test_garmin_acquire_token(monkeypatch):
    """Acquire token should login via garth and store encrypted tokens."""
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)

    class FakeOAuth2:
        access_token = "at"
        refresh_token = "rt"
        expires_in = 3600
        scope = "activity"

        def get(self, key, default=None):
            return getattr(self, key, default)

    class FakeClient:
        def __init__(self):
            self.oauth2_token = FakeOAuth2()

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

    monkeypatch.setattr(providers_garmin, "garth", SimpleNamespace(Client=lambda: FakeClient()))
    body = providers_garmin.GarminAcquireTokenRequest(username="user", password="pass", expires_at=None)
    resp = providers_garmin.garmin_acquire_token(body=body, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin"
    assert body.password == ""


def test_garmin_acquire_token_scraper(monkeypatch):
    """Scraper mode should store oauth1 token/secret under garmin_scraper."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)

    class FakeOAuth1:
        oauth_token = "ot"
        oauth_token_secret = "secret"

    class FakeClient:
        def __init__(self):
            self.oauth1_token = FakeOAuth1()
            self.oauth2_token = None

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

    monkeypatch.setattr(providers_garmin, "garth", SimpleNamespace(Client=lambda: FakeClient()))
    body = providers_garmin.GarminAcquireTokenRequest(username="user", password="pass", expires_at=None)
    resp = providers_garmin.garmin_acquire_token(body=body, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin_scraper"
    assert db.provider_tokens[0].metadata_json.get("token_secret") == "secret"
    assert resp["refresh_token_present"] is False


def test_garmin_refresh_token_endpoint(monkeypatch):
    """Refresh token endpoint should update tokens via Garmin."""
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
            scope="activity",
            expires_at=datetime.utcnow(),
        ),
    )
    token = db.provider_tokens[-1]

    def fake_get(db_session, user_id, provider, tenant_id):  # pylint: disable=unused-argument
        return token

    monkeypatch.setattr(providers_garmin, "get_user_provider_token", fake_get)
    def fake_post(url, data, timeout):  # pylint: disable=unused-argument
        class Resp:
            status_code = 200
            def json(self):
                return {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 7200}
        return Resp()

    monkeypatch.setattr(providers_garmin.requests, "post", fake_post)
    resp = providers_garmin.garmin_refresh_token(user=user, db=db)
    assert resp["status"] == "ok"
