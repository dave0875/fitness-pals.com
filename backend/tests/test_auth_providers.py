"""Tests around multi-provider OAuth flows."""

# pylint: disable=redefined-outer-name

import importlib
import os
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
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
os.environ.setdefault(
    "RUNTRAINER_OIDC_ISSUER", "https://auth.fitness-pals.com/application/o/fitness-pals-web/"
)
os.environ.setdefault("RUNTRAINER_OIDC_CLIENT_ID", "test-oidc-client")
os.environ.setdefault("RUNTRAINER_OIDC_CLIENT_SECRET", "test-oidc-secret")
os.environ.setdefault(
    "RUNTRAINER_OIDC_REDIRECT_URI", "https://example.com/auth/callback"
)

import app.auth.oauth as oauth_mod
from app import main
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


class SessionAwareClient(FakeClient):
    """OAuth client stub that requires request.session to exist."""

    def __init__(self, provider: str):
        super().__init__(provider)
        self.seen_session = False

    async def authorize_redirect(self, request: Request, redirect_uri: str):
        """Touch request.session so missing SessionMiddleware fails loudly."""
        request.session["oauth_provider"] = self.provider
        self.seen_session = True
        return await super().authorize_redirect(request, redirect_uri)


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
    monkeypatch.delenv("RUNTRAINER_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("RUNTRAINER_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("RUNTRAINER_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("RUNTRAINER_OIDC_REDIRECT_URI", raising=False)
    monkeypatch.delenv("RUNTRAINER_WEB_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("RUNTRAINER_WEB_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("RUNTRAINER_WEB_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("RUNTRAINER_WEB_OIDC_REDIRECT_URI", raising=False)
    monkeypatch.delenv("RUNTRAINER_WEB_OIDC_SCOPE", raising=False)

    # Reload module to pick up the env
    importlib.reload(oauth_mod)
    return oauth_mod


def test_discovery_url_uses_authentik_application_issuer():
    """Authentik login should use the issuer discovery document."""
    issuer = "https://auth.fitness-pals.com/application/o/fitness-pals-web/"

    assert (
        oauth_mod._discovery_url_for_issuer(issuer)  # pylint: disable=protected-access
        == "https://auth.fitness-pals.com/application/o/fitness-pals-web/.well-known/openid-configuration"
    )


def test_reload_registers_authentik_provider_from_oidc_issuer(monkeypatch):
    """Reloading auth config should register the Authentik broker via discovery."""
    registrations: list[dict[str, object]] = []

    def fake_register(self, name=None, **kwargs):  # pylint: disable=unused-argument
        registrations.append({"name": name, **kwargs})

    monkeypatch.setattr("authlib.integrations.starlette_client.OAuth.register", fake_register)
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/fitness-pals-web/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "oidc-secret")
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_REDIRECT_URI",
        "https://fitness-pals.com/auth/callback",
    )

    reloaded = importlib.reload(oauth_mod)

    assert "authentik" in reloaded._registered  # pylint: disable=protected-access
    assert reloaded._redirect_uri_for("authentik") == "https://fitness-pals.com/auth/callback"
    assert any(
        registration == {
            "name": "authentik",
            "server_metadata_url": "https://auth.fitness-pals.com/application/o/fitness-pals-web/.well-known/openid-configuration",
            "client_id": "oidc-client",
            "client_secret": "oidc-secret",
            "client_kwargs": {"scope": "openid email profile"},
        }
        for registration in registrations
    )


def test_web_oidc_config_overrides_generic_oidc_settings(monkeypatch):
    """Backend web login should prefer website-specific OIDC settings when present."""
    monkeypatch.setenv(
        "RUNTRAINER_WEB_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/fitness-pals-web/",
    )
    monkeypatch.setenv("RUNTRAINER_WEB_OIDC_CLIENT_ID", "web-oidc-client")
    monkeypatch.setenv("RUNTRAINER_WEB_OIDC_CLIENT_SECRET", "web-oidc-secret")
    monkeypatch.setenv(
        "RUNTRAINER_WEB_OIDC_REDIRECT_URI",
        "https://fitness-pals.com/auth/callback",
    )
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "gpt-oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "gpt-oidc-secret")

    reloaded = importlib.reload(oauth_mod)

    assert reloaded._oidc_issuer() == "https://auth.fitness-pals.com/application/o/fitness-pals-web/"
    assert reloaded._oidc_client_id() == "web-oidc-client"
    assert reloaded._oidc_client_secret() == "web-oidc-secret"
    assert reloaded._redirect_uri_for("authentik") == "https://fitness-pals.com/auth/callback"


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

    request = Request(scope={"type": "http", "query_string": b"", "headers": [], "session": {}})
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

    request = Request(scope={"type": "http", "query_string": b"", "headers": [], "session": {}})
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


@pytest.mark.asyncio
async def test_login_alias_uses_authentik_provider(monkeypatch):
    """The default /auth/login alias should use the Authentik broker."""
    monkeypatch.setenv(
        "RUNTRAINER_WEB_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/fitness-pals-web/",
    )
    monkeypatch.setenv("RUNTRAINER_WEB_OIDC_CLIENT_ID", "web-oidc-client")
    monkeypatch.setenv("RUNTRAINER_WEB_OIDC_CLIENT_SECRET", "web-oidc-secret")
    monkeypatch.setenv(
        "RUNTRAINER_WEB_OIDC_REDIRECT_URI",
        "https://example.com/auth/callback",
    )
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "gpt-oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "gpt-oidc-secret")
    reloaded = importlib.reload(oauth_mod)
    fake_client = FakeClient(reloaded.DEFAULT_PROVIDER)
    reloaded._registered[reloaded.DEFAULT_PROVIDER] = True  # pylint: disable=protected-access
    setattr(reloaded.oauth, reloaded.DEFAULT_PROVIDER, fake_client)

    next_path = "/welcome?step=connect"
    request = Request(
        scope={
            "type": "http",
            "query_string": f"next={quote(next_path, safe='')}".encode(),
            "headers": [],
        }
    )
    response = await reloaded.login_google(request)

    assert isinstance(response, RedirectResponse)
    assert fake_client.redirects == ["https://example.com/auth/callback"]
    cookies = response.headers.getlist("set-cookie")
    assert any("runtrainer_auth_next=" in cookie and "step=connect" in cookie for cookie in cookies)


def test_auth_login_route_supports_session_backed_redirects(monkeypatch):
    """The app-level /auth/login route should expose request.session for OAuth state handling."""
    fake_client = SessionAwareClient("authentik")
    monkeypatch.setitem(oauth_mod._registered, "authentik", True)  # pylint: disable=protected-access
    monkeypatch.setitem(oauth_mod._registered, "google", True)  # pylint: disable=protected-access
    monkeypatch.setattr(oauth_mod.oauth, "authentik", fake_client, raising=False)
    monkeypatch.setattr(oauth_mod.oauth, "google", fake_client, raising=False)

    client = TestClient(main.app)
    response = client.get("/auth/login?next=/welcome", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert fake_client.seen_session is True
    assert "runtrainer_auth_next=" in response.headers.get("set-cookie", "")
