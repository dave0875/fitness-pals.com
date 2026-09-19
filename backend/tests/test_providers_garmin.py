"""Tests for Garmin OAuth login and callback flows."""

from __future__ import annotations

import os
import uuid
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests_mock
from fastapi import HTTPException

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

from app.routes import providers_garmin
from app.services import garmin_ingest
from app.services.providers import ProviderTokenDetails, save_user_provider_token
from app.types import CurrentUserLike
from app.models import UserProviderToken


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
        if _model is UserProviderToken:
            return FakeQuery(self.provider_tokens)
        return FakeQuery(self.items)

    def add(self, obj):
        self.items.append(obj)
        self.added_runs.append(obj)
        if isinstance(obj, UserProviderToken):
            self.provider_tokens.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def _fake_user(tenant_id=None) -> CurrentUserLike:
    class FakeUser:
        def __init__(self, tenant=None):
            self.id = uuid.uuid4()
            self.tenant_id = tenant

    return FakeUser(tenant_id)


GARMIN_DEFAULT_TOKEN_URL = "https://connectapi.garmin.com/di-oauth2-service/oauth/token"


def _test_token_url():
    return os.environ.get("GARMIN_TOKEN_URL", GARMIN_DEFAULT_TOKEN_URL)


def test_login_builds_redirect(monkeypatch):
    """Login endpoint should build a Garmin auth URL with configured env."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    fake_request = SimpleNamespace(query_params={})
    resp = providers_garmin.garmin_login(fake_request, _fake_user())
    assert resp.status_code in (302, 307)
    assert "response_type=code" in resp.headers["location"]
    assert "client_id=cid" in resp.headers["location"]
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in resp.headers["location"]
    assert urlparse(resp.headers["location"]).path == "/oauth2Confirm"
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    verifier = next(
        cookie.split(";", 1)[0].split("=", 1)[1]
        for cookie in resp.headers.getlist("set-cookie")
        if cookie.startswith("garmin_pkce_verifier=")
    )
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert "scope" not in query


def test_login_persists_safe_next_redirect(monkeypatch):
    """Garmin login should preserve a safe next redirect in a cookie."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    fake_request = SimpleNamespace(query_params={"next": "/welcome?garmin=connected"})
    resp = providers_garmin.garmin_login(fake_request, _fake_user())
    assert resp.status_code in (302, 307)
    cookies = resp.headers.getlist("set-cookie")
    assert any("garmin_oauth_next=" in cookie and "welcome" in cookie for cookie in cookies)


def test_scraper_login_does_not_redirect_to_unusable_web_signin(monkeypatch):
    """Normal Connect sign-in does not authorize a third-party app."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_login(SimpleNamespace(query_params={}), _fake_user())
    assert exc.value.status_code == 503


def test_sso_callback_stores_encrypted_thirty_day_garmin_grant(monkeypatch):
    """A Garmin service ticket becomes an encrypted, 30-day connection grant."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = _fake_user()

    class FakeGarminConnectClient:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.di_token = None
            self.di_refresh_token = None
            self.di_client_id = None

        def exchange_service_ticket(self, ticket, service_url):
            assert ticket == "ST-one-time-ticket"
            assert service_url.endswith("/sso/callback/expected-state")
            self.di_token = "garmin-access-token"
            self.di_refresh_token = "garmin-refresh-token"
            self.di_client_id = "garmin-client"

        def connectapi(self, path):
            assert path == "/userprofile-service/socialProfile"
            return {"displayName": "athlete-42"}

    monkeypatch.setattr(
        providers_garmin, "GarminConnectSSOClient", FakeGarminConnectClient
    )
    request = SimpleNamespace(
        cookies={
            "garmin_oauth_state": "expected-state",
            "garmin_oauth_next": "/welcome",
        },
        url_for=lambda name, state: (
            f"https://fitness-pals.com/api/providers/garmin/sso/callback/{state}"
        ),
    )

    response = providers_garmin.garmin_sso_callback(
        request=request,
        state="expected-state",
        ticket="ST-one-time-ticket",
        user=user,
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/welcome"
    stored = db.provider_tokens[0]
    assert stored.provider == "garmin_scraper"
    assert stored.access_token_encrypted != b"garmin-access-token"
    assert stored.refresh_token_encrypted != b"garmin-refresh-token"
    assert stored.provider_user_id == "athlete-42"
    assert stored.metadata_json["auth_scheme"] == "garmin_connect_sso"
    assert stored.metadata_json["di_client_id"] == "garmin-client"
    remaining = stored.expires_at - datetime.now(timezone.utc)
    assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)


def test_sso_callback_rejects_state_mismatch(monkeypatch):
    """A service ticket cannot be linked through a forged callback."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    request = SimpleNamespace(
        cookies={"garmin_oauth_state": "expected-state"},
        url_for=lambda name, state: (
            f"https://fitness-pals.com/api/providers/garmin/sso/callback/{state}"
        ),
    )

    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_sso_callback(
            request=request,
            state="forged-state",
            ticket="ST-one-time-ticket",
            user=_fake_user(),
            db=FakeSession(),
        )

    assert exc.value.status_code == 400


def test_callback_happy_path(monkeypatch):
    """Callback should exchange code and store encrypted tokens."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
    token_url = _test_token_url()
    fake_request = SimpleNamespace(cookies={
        "garmin_oauth_state": "abc", "garmin_pkce_verifier": "verifier",
        "garmin_oauth_user": str(user.id),
    })
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
        result = providers_garmin.garmin_callback(request=fake_request, code="abc", state="abc", user=user, db=db)
        assert m.last_request.text is not None
        assert "code_verifier=verifier" in m.last_request.text
    assert result.status_code in (302, 303, 307)
    assert result.headers["location"] == "/welcome?garmin=connected"
    assert db.items, "Token should be saved"
    stored = db.items[0]
    assert stored.provider == "garmin"
    assert stored.access_token_encrypted != b"at"
    assert stored.refresh_token_encrypted != b"rt"
    assert stored.expires_at and isinstance(stored.expires_at, datetime)
    assert stored.tenant_id is None


def test_callback_redirects_to_safe_next_when_present(monkeypatch):
    """Garmin callback should redirect to the preserved safe next path."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
    token_url = _test_token_url()
    fake_request = SimpleNamespace(
        cookies={
            "garmin_oauth_state": "abc",
            "garmin_pkce_verifier": "verifier",
            "garmin_oauth_user": str(user.id),
            "garmin_oauth_next": "/welcome?garmin=connected",
        }
    )
    with requests_mock.Mocker() as m:
        m.post(
            token_url,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
            status_code=200,
            headers={"content-type": "application/json"},
        )
        result = providers_garmin.garmin_callback(
            request=fake_request, code="abc", state="abc", user=user, db=db
        )
    assert result.status_code in (302, 303, 307)
    assert result.headers["location"] == "/welcome?garmin=connected"


def test_callback_missing_code(monkeypatch):
    """Callback should fail when no code is provided."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    fake_request = SimpleNamespace(cookies={"garmin_oauth_state": "abc"})
    with pytest.raises(HTTPException):
        providers_garmin.garmin_callback(request=fake_request, code=None, state="abc", user=_fake_user(), db=FakeSession())


def test_callback_requires_pkce_verifier(monkeypatch):
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_callback(
            request=SimpleNamespace(cookies={"garmin_oauth_state": "abc"}),
            code="code", state="abc", user=_fake_user(), db=FakeSession(),
        )
    assert exc.value.status_code == 400


def test_callback_rejects_different_signed_in_user(monkeypatch):
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_callback(
            request=SimpleNamespace(cookies={
                "garmin_oauth_state": "abc", "garmin_pkce_verifier": "verifier",
                "garmin_oauth_user": str(uuid.uuid4()),
            }),
            code="code", state="abc", user=_fake_user(), db=FakeSession(),
        )
    assert exc.value.status_code == 400


def test_refresh_happy_path(monkeypatch):
    """Refresh endpoint should rotate tokens when refresh token is present."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
    # Seed existing token
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="old-at",
            refresh_token="old-rt",
            metadata={"auth_scheme": "garmin_official_oauth2"},
        ),
    )
    token_url = _test_token_url()
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
    assert stored.metadata_json["auth_scheme"] == "garmin_official_oauth2"


def test_refresh_reauth_when_missing_refresh(monkeypatch):
    """Refresh endpoint should require reauth when no refresh token stored."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
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
    """Batch fetch should queue work for each user and report errors."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    db = FakeSession()
    user1 = _fake_user()
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
    summary = providers_garmin.garmin_fetch_all(_fake_user(), db=db)
    assert summary == {"status": "queued", "queued": 1, "errors": 0}


def test_token_status_allows_clock_skew(monkeypatch):
    """Token status should not immediately report expired when slightly in the past."""
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    db = FakeSession()
    user = _fake_user()
    # Seed a token that expired 1 minute ago; should still be considered active due to grace period.
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="at",
            refresh_token="rt",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )
    status = providers_garmin.garmin_token_status(user=user, db=db)
    assert status["status"] == "active"
    assert status["seconds_remaining"] == 0
    assert status["provider"] == "garmin"
    assert status["mode"] == "oauth"


def test_token_status_respects_garmin_mode(monkeypatch):
    """Status should return only the token matching GARMIN_MODE."""
    db = FakeSession()
    user = _fake_user()
    # Older garmin token
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin",
            access_token="old",
            refresh_token="old-r",
            expires_at=datetime.utcnow() + timedelta(days=1),
        ),
    )
    # Newer scraper token
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="new",
            refresh_token=None,
            expires_at=datetime.utcnow() + timedelta(days=2),
        ),
    )
    # scraper mode should return scraper token
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    status = providers_garmin.garmin_token_status(user=user, db=db)
    assert status["provider"] == "garmin_scraper"
    # oauth mode should return garmin token
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    status = providers_garmin.garmin_token_status(user=user, db=db)
    assert status["provider"] == "garmin"


def test_refresh_reauth_on_failure(monkeypatch):
    """Refresh endpoint should require reauth when Garmin token refresh fails."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
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
    token_url = _test_token_url()
    with requests_mock.Mocker() as m:
        m.post(token_url, status_code=400)
        with pytest.raises(HTTPException) as exc:
            providers_garmin.garmin_refresh(user=user, db=db)
    assert exc.value.status_code == 410


def test_fetch_happy_path(monkeypatch):
    """Fetch endpoint should queue work and return the queued job id."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = _fake_user()
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
    class FakeClient:  # pylint: disable=too-few-public-methods
        def connectapi(self, *_args, **_kwargs):
            return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=FakeClient, auth=None))
    class FakeWriteAPI:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.records = []

        def write(self, bucket=None, org=None, record=None):  # pylint: disable=unused-argument
            self.records.extend(record or [])

    class FakeInfluxClient:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.org = "org"
            self.default_bucket = "bucket"
            self.write_api_obj = FakeWriteAPI()

        def write_api(self):
            return self.write_api_obj

        def query_api(self):
            return SimpleNamespace(query=lambda **_kwargs: [])

        def delete_api(self):
            return SimpleNamespace(delete=lambda **_kwargs: None)

    def fake_influx_client():
        return FakeInfluxClient()

    monkeypatch.setattr(garmin_ingest, "get_operator_influx_client", fake_influx_client)

    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["sync_job_id"]
    assert resp["ingested"] == 0
    assert resp["test_run"] is False


def test_fetch_rejects_official_grant_before_queueing(monkeypatch):
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    db = FakeSession()
    user = _fake_user()
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id, tenant_id=None, provider="garmin",
            access_token="at", refresh_token="rt",
            metadata={"auth_scheme": "garmin_official_oauth2"},
        ),
    )
    with pytest.raises(HTTPException) as exc:
        providers_garmin.garmin_fetch(user=user, db=db)
    assert exc.value.status_code == 503


def test_fetch_reauth_when_missing_token(monkeypatch):
    """Fetch should still enqueue work even when a token is missing."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    db = FakeSession()
    user = _fake_user()
    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["ingested"] == 0


def test_fetch_reauth_on_401(monkeypatch):
    """Fetch should enqueue work even if a later worker fetch would 401."""
    monkeypatch.setenv("GARMIN_CLIENT_ID", "cid")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("GARMIN_API_BASE", "https://mock.garmin")
    db = FakeSession()
    user = _fake_user()
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
    class FakeClient:  # pylint: disable=too-few-public-methods
        def connectapi(self, *_args, **_kwargs):
            raise HTTPException(status_code=410, detail="Garmin reauth required")

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=FakeClient, auth=None))
    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["ingested"] == 0


def test_scraper_token_endpoint():
    """Scraper token endpoint should store access token without credentials."""
    db = FakeSession()
    user = _fake_user()
    req = providers_garmin.ScraperTokenRequest(scraper_access_token="scraper-at", token_secret="scraper-secret")
    resp = providers_garmin.garmin_scraper_token(body=req, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin_scraper"
    assert db.provider_tokens[0].refresh_token_encrypted is None
    assert db.provider_tokens[0].metadata_json.get("token_secret") == "scraper-secret"


def test_scraper_fetch_happy_path(monkeypatch):
    """Scraper mode fetch should queue work and succeed."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = _fake_user()
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="scraper-at",
        ),
    )
    class FakeClient:  # pylint: disable=too-few-public-methods
        def connectapi(self, *_args, **_kwargs):
            return [{"id": 1}]

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=FakeClient, auth=None))
    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["sync_job_id"]
    assert resp["ingested"] == 0


def test_scraper_fetch_reauth_missing_token(monkeypatch):
    """Scraper mode should enqueue work even when a token is missing."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = _fake_user()
    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["ingested"] == 0


def test_scraper_fetch_reauth_on_401(monkeypatch):
    """Scraper mode should enqueue work even if the worker later 401s."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = _fake_user()
    providers_garmin.save_user_provider_token(
        db,
        providers_garmin.ProviderTokenDetails(
            user_id=user.id,
            tenant_id=None,
            provider="garmin_scraper",
            access_token="scraper-at",
        ),
    )
    class FakeClient:  # pylint: disable=too-few-public-methods
        def connectapi(self, *_args, **_kwargs):
            raise HTTPException(status_code=410, detail="Garmin reauth required")

    monkeypatch.setattr(garmin_ingest, "garth", SimpleNamespace(Client=FakeClient, auth=None))
    resp = providers_garmin.garmin_fetch(user=user, db=db)
    assert resp["status"] == "queued"
    assert resp["ingested"] == 0


def test_garmin_acquire_token(monkeypatch):
    """Acquire token should login via garth and store encrypted tokens."""
    monkeypatch.setenv("GARMIN_MODE", "oauth")
    db = FakeSession()
    user = _fake_user()

    class FakeOAuth2:  # pylint: disable=too-few-public-methods
        access_token = "at"
        refresh_token = "rt"
        expires_in = 3600
        scope = "activity"

        def get(self, key, default=None):
            return getattr(self, key, default)

    class FakeClient:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.oauth2_token = FakeOAuth2()

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

    monkeypatch.setattr(providers_garmin, "garth", SimpleNamespace(Client=FakeClient))
    body = providers_garmin.GarminAcquireTokenRequest(username="user", password="pass", expires_at=None)
    resp = providers_garmin.garmin_acquire_token(body=body, user=user, db=db)
    assert resp["status"] == "ok"
    assert db.provider_tokens[0].provider == "garmin"
    assert body.password == ""


def test_garmin_acquire_token_scraper(monkeypatch):
    """Scraper mode should store oauth1 token/secret under garmin_scraper."""
    monkeypatch.setenv("GARMIN_MODE", "scraper")
    db = FakeSession()
    user = _fake_user()

    class FakeOAuth1:  # pylint: disable=too-few-public-methods
        oauth_token = "ot"
        oauth_token_secret = "secret"

    class FakeClient:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.oauth1_token = FakeOAuth1()
            self.oauth2_token = None

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

    monkeypatch.setattr(providers_garmin, "garth", SimpleNamespace(Client=FakeClient))
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
    user = _fake_user()
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
        class Resp:  # pylint: disable=too-few-public-methods
            status_code = 200
            def json(self):
                return {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 7200}
        return Resp()

    monkeypatch.setattr(providers_garmin.requests, "post", fake_post)
    resp = providers_garmin.garmin_refresh_token(user=user, db=db)
    assert resp["status"] == "ok"
