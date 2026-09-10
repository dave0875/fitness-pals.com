"""Authorization regression tests for shared provider applications."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")

from app import deps, main  # noqa: E402  pylint: disable=wrong-import-position
from app.models import ProviderApp, UserProviderToken  # noqa: E402  pylint: disable=wrong-import-position


class FakeQuery:
    """Small query stub for provider app and token route tests."""

    def __init__(self, items):
        self.items = items

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class FakeSession:
    """Store provider records in memory while exercising route dependencies."""

    def __init__(self):
        self.app = SimpleNamespace(
            id=uuid4(),
            provider="garmin",
            display_name="Garmin",
            client_id="shared-client",
            client_secret_encrypted=b"encrypted",
            auth_url="https://example.com/authorize",
            token_url="https://example.com/token",
            scopes="activity",
            created_at=None,
            updated_at=None,
        )
        self.tokens = []

    def query(self, model):
        if model is ProviderApp:
            return FakeQuery([self.app])
        if model is UserProviderToken:
            return FakeQuery(self.tokens)
        raise AssertionError(f"Unexpected model query: {model}")

    def add(self, obj):
        if isinstance(obj, UserProviderToken):
            self.tokens.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


@pytest.fixture
def provider_client():
    """Return a test client and clean dependency overrides after each test."""
    db = FakeSession()
    client = TestClient(main.app)
    main.app.dependency_overrides[deps.get_db] = lambda: db
    try:
        yield client, db
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/providers/apps", None),
        (
            "post",
            "/api/providers/apps",
            {"provider": "garmin", "client_id": "replacement-client"},
        ),
        ("get", "/api/providers/garmin/app", None),
    ],
)
def test_athlete_cannot_manage_shared_provider_apps(
    provider_client, method, path, json_body
):
    """Authenticated athletes must not read or mutate global OAuth clients."""
    client, _db = provider_client
    athlete = SimpleNamespace(id=uuid4(), role="athlete")
    main.app.dependency_overrides[deps.get_current_user] = lambda: athlete

    response = client.request(method, path, json=json_body)

    assert response.status_code == 403
    assert response.json() == {"detail": "Administrator access required"}


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/providers/apps", None),
        (
            "post",
            "/api/providers/apps",
            {"provider": "garmin", "client_id": "replacement-client"},
        ),
        ("get", "/api/providers/garmin/app", None),
    ],
)
def test_administrator_can_manage_shared_provider_apps(
    provider_client, method, path, json_body
):
    """Administrators retain access to every shared OAuth client endpoint."""
    client, _db = provider_client
    administrator = SimpleNamespace(id=uuid4(), role="administrator")
    main.app.dependency_overrides[deps.get_current_user] = lambda: administrator

    response = client.request(method, path, json=json_body)

    assert response.status_code == 200


def test_athlete_can_store_only_their_provider_connection(provider_client):
    """The personal connection route remains available and uses the current user id."""
    client, db = provider_client
    athlete = SimpleNamespace(id=uuid4(), role="athlete")
    main.app.dependency_overrides[deps.get_current_user] = lambda: athlete

    response = client.post(
        "/api/providers/garmin/connect",
        json={"access_token": "athlete-access", "refresh_token": "athlete-refresh"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(athlete.id)
    assert len(db.tokens) == 1
    assert db.tokens[0].user_id == athlete.id
