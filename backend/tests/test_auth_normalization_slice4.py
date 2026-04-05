"""Slice 4 auth normalization regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def test_protected_product_route_rejects_raw_google_bearer_token(monkeypatch):
    """Product auth should not fall back to raw Google bearer verification."""
    monkeypatch.setenv("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s=")
    monkeypatch.setenv("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "test-google-client")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_REDIRECT_URI", "https://example.com/auth/google/callback")

    from app import deps

    called = {"google_verify": False}
    deps.settings.google_client_id = "test-google-client"

    def fake_verify(token, request_obj, audience):  # pylint: disable=unused-argument
        called["google_verify"] = True
        return {
            "email": "raw-google@example.com",
            "name": "Raw Google User",
            "picture": "http://example.com/pic.png",
        }

    class FakeSession:
        def query(self, model):  # pylint: disable=unused-argument
            return self

        def filter(self, condition):  # pylint: disable=unused-argument
            return self

        def first(self):
            return None

        def add(self, obj):  # pylint: disable=unused-argument
            return None

        def commit(self):
            return None

        def refresh(self, obj):  # pylint: disable=unused-argument
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(deps.google_id_token, "verify_oauth2_token", fake_verify)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="raw-google-token")

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(credentials=creds, db=FakeSession())

    assert exc_info.value.status_code == 401
    assert called["google_verify"] is False


def test_frontend_pages_do_not_bootstrap_from_browser_stored_access_token():
    """Product pages should not read the access token from localStorage."""
    repo_root = Path(__file__).resolve().parents[2]
    dashboard = (repo_root / "frontend/pages/dashboard.js").read_text(encoding="utf-8")
    settings = (repo_root / "frontend/pages/settings.js").read_text(encoding="utf-8")
    pages = dashboard + "\n" + settings

    assert 'localStorage.getItem("access_token")' not in pages
    assert "store your access_token in localStorage" not in pages.lower()
