"""Tests for backend liveness, readiness, and auth middleware wiring."""

from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app import main


def test_backend_health_endpoint():
    """The liveness endpoint should always return ok."""
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_backend_ready_endpoint_returns_ok(monkeypatch):
    """Readiness should return 200 when dependencies are ready."""
    monkeypatch.setattr(
        main,
        "check_backend_ready",
        lambda: (True, {"database": "ok", "schema": "ok"}),
    )
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "schema": "ok"},
    }


def test_backend_ready_endpoint_returns_503(monkeypatch):
    """Readiness should surface dependency failures."""
    monkeypatch.setattr(
        main,
        "check_backend_ready",
        lambda: (False, {"database": "unreachable", "schema": "unknown"}),
    )
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "unreachable", "schema": "unknown"},
    }


def test_backend_installs_session_middleware_for_authlib():
    """OAuth redirects need request.session available on auth routes."""
    middleware_classes = [entry.cls for entry in main.app.user_middleware]

    assert SessionMiddleware in middleware_classes
