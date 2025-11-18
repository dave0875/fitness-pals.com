import importlib
import os
import uuid
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse


class FakeSession:
    def __init__(self):
        self._items = []
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        return obj

    def query(self, model):
        # Return an object that yields no existing user
        return SimpleNamespace(filter=lambda *args, **kwargs: SimpleNamespace(first=lambda: None))


class FakeClient:
    def __init__(self, provider: str):
        self.provider = provider
        self.server_metadata = {"userinfo_endpoint": "https://example.com/userinfo"}
        self.redirects = []
        self.access_tokens = []

    async def authorize_redirect(self, request: Request, redirect_uri: str):
        self.redirects.append(redirect_uri)
        return RedirectResponse(redirect_uri)

    async def authorize_access_token(self, request: Request):
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
        return token.get("userinfo")

    async def parse_id_token(self, request: Request, token):
        # Fallback path if userinfo endpoint isn't used
        return token.get("userinfo")


@pytest.fixture()
def reload_oauth(monkeypatch):
    # Ensure env vars exist so providers register
    monkeypatch.setenv("RUNTRAINER_JWT_SECRET", "test")
    monkeypatch.setenv("RUNTRAINER_FERNET_KEY", "ZmFrZS1mZXJuZXQta2V5LWRvLW5vdC11c2U=")
    monkeypatch.setenv("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
    for provider in ("GOOGLE", "MICROSOFT", "APPLE"):
        monkeypatch.setenv(f"RUNTRAINER_{provider}_CLIENT_ID", f"{provider.lower()}-id")
        monkeypatch.setenv(f"RUNTRAINER_{provider}_CLIENT_SECRET", f"{provider.lower()}-secret")
        monkeypatch.setenv(
            f"RUNTRAINER_{provider}_REDIRECT_URI", f"https://example.com/auth/{provider.lower()}/callback"
        )

    # Reload module to pick up the env
    import app.auth.oauth as oauth_mod

    importlib.reload(oauth_mod)
    return oauth_mod


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft", "apple"])
async def test_login_and_callback_with_stubbed_oidc(provider, reload_oauth):
    oauth_mod = reload_oauth
    fake_client = FakeClient(provider)
    # Ensure provider is considered registered
    oauth_mod._registered[provider] = True
    setattr(oauth_mod.oauth, provider, fake_client)

    request = Request(scope={"type": "http"})
    resp = await oauth_mod.login(provider, request)
    assert isinstance(resp, RedirectResponse)
    assert fake_client.redirects, "authorize_redirect should be called"

    db = FakeSession()
    callback_resp = await oauth_mod.auth_callback(provider, request, db=db)
    # Should yield app JWTs regardless of provider
    assert "access_token" in callback_resp
    assert "refresh_token" in callback_resp


@pytest.mark.asyncio
async def test_missing_provider_raises(reload_oauth):
    oauth_mod = reload_oauth
    request = Request(scope={"type": "http"})
    with pytest.raises(Exception):
        await oauth_mod.login("unknown", request)
