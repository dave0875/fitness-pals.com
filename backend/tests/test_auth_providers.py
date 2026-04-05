"""Tests around multi-provider OAuth flows."""

# pylint: disable=redefined-outer-name

import importlib
import os
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test")
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

import app.auth.oauth as oauth_mod
from app.utils.security import APP_REFRESH_COOKIE, APP_SESSION_COOKIE


class FakeSession:
    """Minimal DB session stub."""

    def __init__(self):
        """Initialize with empty storage."""
        self._items = []
        self.added = []

    def add(self, obj):
        """Record added objects."""
        self.added.append(obj)

    def commit(self):
        """No-op commit."""
        return None

    def refresh(self, obj):
        """Return the refreshed object."""
        return obj

    def query(self, _model):
        """Return an object that yields no existing user."""
        return SimpleNamespace(filter=lambda *args, **kwargs: SimpleNamespace(first=lambda: None))


class FakeClient:
    """Simple OAuth client stub that tracks redirects/tokens."""

    def __init__(self, provider: str):
        """Initialize with canned metadata."""
        self.provider = provider
        self.server_metadata = {"userinfo_endpoint": "https://example.com/userinfo"}
        self.redirects: list[str] = []
        self.access_tokens: list[dict] = []

    async def authorize_redirect(self, _request: Request, redirect_uri: str):
        """Simulate redirect flow."""
        self.redirects.append(redirect_uri)
        return RedirectResponse(redirect_uri)

    async def authorize_access_token(self, _request: Request):
        """Return a fake access token payload."""
        token = {
            "access_token": f"token-{self.provider}",
            "userinfo": {
                "email": f"{self.provider}@example.com",
                "name": f"{self.provider}-user",
                "picture": "http://example.com/pic.png",
            },
        }
        self.access_tokens.append(token)
        return token

    async def userinfo(self, token):
        """Return stored userinfo payload."""
        return token.get("userinfo")

    async def parse_id_token(self, _request: Request, token):
        """Fallback path if userinfo endpoint isn't used."""
        return token.get("userinfo")


@pytest.fixture()
def reload_oauth(monkeypatch):
    """Reload the OAuth module after injecting env vars for providers."""
    # Ensure env vars exist so providers register
    monkeypatch.setenv("RUNTRAINER_JWT_SECRET", "test")
    monkeypatch.setenv(
        "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
    )
    monkeypatch.setenv("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
    for provider in ("GOOGLE", "MICROSOFT", "APPLE"):
        monkeypatch.setenv(f"RUNTRAINER_{provider}_CLIENT_ID", f"{provider.lower()}-id")
        monkeypatch.setenv(f"RUNTRAINER_{provider}_CLIENT_SECRET", f"{provider.lower()}-secret")
        monkeypatch.setenv(
            f"RUNTRAINER_{provider}_REDIRECT_URI",
            f"https://example.com/auth/{provider.lower()}/callback",
        )

    # Reload module to pick up the env
    importlib.reload(oauth_mod)
    return oauth_mod


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft", "apple"])
async def test_login_and_callback_with_stubbed_oidc(provider, reload_oauth):
    """Login + callback should succeed per provider using fake client."""
    oauth_mod = reload_oauth
    fake_client = FakeClient(provider)
    # Ensure provider is considered registered
    oauth_mod._registered[provider] = True  # pylint: disable=protected-access
    setattr(oauth_mod.oauth, provider, fake_client)

    request = Request(scope={"type": "http", "query_string": b"", "headers": []})
    resp = await oauth_mod.login(provider, request)
    assert isinstance(resp, RedirectResponse)
    assert fake_client.redirects, "authorize_redirect should be called"

    db = FakeSession()
    callback_resp = await oauth_mod.auth_callback(provider, request, db=db)
    assert isinstance(callback_resp, RedirectResponse)
    assert callback_resp.headers["location"] == "/welcome"
    cookies = callback_resp.headers.getlist("set-cookie")
    assert any(APP_SESSION_COOKIE in cookie for cookie in cookies)
    assert any(APP_REFRESH_COOKIE in cookie for cookie in cookies)


@pytest.mark.asyncio
async def test_login_persists_safe_next_redirect(reload_oauth):
    """Login should preserve a safe next redirect across the OAuth handshake."""
    oauth_mod = reload_oauth
    fake_client = FakeClient("google")
    oauth_mod._registered["google"] = True  # pylint: disable=protected-access
    setattr(oauth_mod.oauth, "google", fake_client)

    request = Request(
        scope={
            "type": "http",
            "query_string": b"next=%2Fwelcome",
            "headers": [],
        }
    )
    resp = await oauth_mod.login("google", request)

    assert isinstance(resp, RedirectResponse)
    cookies = resp.headers.getlist("set-cookie")
    assert any("runtrainer_auth_next=" in cookie and "welcome" in cookie for cookie in cookies)


@pytest.mark.asyncio
async def test_callback_redirects_to_safe_next_when_present(reload_oauth):
    """Callback should redirect to the safe next path captured during login."""
    oauth_mod = reload_oauth
    fake_client = FakeClient("google")
    oauth_mod._registered["google"] = True  # pylint: disable=protected-access
    setattr(oauth_mod.oauth, "google", fake_client)

    request = Request(scope={"type": "http", "query_string": b"", "headers": []})
    request._cookies = {"runtrainer_auth_next": "/welcome"}  # pylint: disable=protected-access

    db = FakeSession()
    callback_resp = await oauth_mod.auth_callback("google", request, db=db)

    assert isinstance(callback_resp, RedirectResponse)
    assert callback_resp.headers["location"] == "/welcome"


@pytest.mark.asyncio
async def test_callback_rejects_unsafe_next_redirect(reload_oauth):
    """Unsafe absolute next targets should be ignored in favor of a safe default."""
    oauth_mod = reload_oauth
    fake_client = FakeClient("google")
    oauth_mod._registered["google"] = True  # pylint: disable=protected-access
    setattr(oauth_mod.oauth, "google", fake_client)

    request = Request(scope={"type": "http", "query_string": b"", "headers": []})
    request._cookies = {"runtrainer_auth_next": "https://evil.example.com"}  # pylint: disable=protected-access

    db = FakeSession()
    callback_resp = await oauth_mod.auth_callback("google", request, db=db)

    assert isinstance(callback_resp, RedirectResponse)
    assert callback_resp.headers["location"] == "/welcome"


@pytest.mark.asyncio
async def test_missing_provider_raises(reload_oauth):
    """Unknown providers should raise when login is attempted."""
    oauth_mod = reload_oauth
    request = Request(scope={"type": "http", "query_string": b"", "headers": []})
    with pytest.raises(Exception):
        await oauth_mod.login("unknown", request)
