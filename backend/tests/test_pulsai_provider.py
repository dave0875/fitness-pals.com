"""Tests for the PulsAI MCP Garmin bridge thin slice."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter


os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")


from app.models import Activity, ActivitySource
from app.providers import pulsai
from app.routes import providers_pulsai
from app.services import sync_jobs


class FakeQuery:
    def __init__(self, data):
        self.data = list(data)

    def filter(self, *conditions):
        return FakeQuery(
            [item for item in self.data if all(self._matches(c, item) for c in conditions)]
        )

    def first(self):
        return self.data[0] if self.data else None

    @staticmethod
    def _resolve(side, item):
        if isinstance(side, BindParameter):
            return side.value
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        return getattr(item, attr) if attr and hasattr(item, attr) else side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            values = [self._matches(c, item) for c in condition.clauses]
            return all(values) if condition.operator is operators.and_ else any(values)
        if isinstance(condition, BinaryExpression):
            return condition.operator(
                self._resolve(condition.left, item),
                self._resolve(condition.right, item),
            )
        return True


class FakeSession:
    def __init__(self):
        self.items = []

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        return obj

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def get(self, _model, _ident):
        return None


def test_endpoint_validation_allows_only_https_pulsai_hosts(monkeypatch):
    monkeypatch.delenv("RUNTRAINER_PULSAI_ALLOWED_HOSTS", raising=False)
    endpoint, host = providers_pulsai._validated_endpoint(
        SecretStr("https://mcp.pulsai.me/private/opaque")
    )
    assert endpoint.startswith("https://mcp.pulsai.me/")
    assert host == "mcp.pulsai.me"

    with pytest.raises(HTTPException):
        providers_pulsai._validated_endpoint(SecretStr("http://pulsai.me/private"))
    with pytest.raises(HTTPException):
        providers_pulsai._validated_endpoint(SecretStr("https://pulsai.me.evil.test/x"))


def test_pulsai_adapter_is_registered():
    assert isinstance(sync_jobs.get_provider_adapter("pulsai"), pulsai.PulsaiProvider)


def test_pulsai_ingest_is_tenant_scoped_idempotent_and_tracks_provenance(monkeypatch):
    db = FakeSession()
    tenant_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id)
    token = SimpleNamespace(
        user_id=user.id,
        tenant_id=tenant_id,
        provider="pulsai",
        metadata_json={"endpoint_host": "mcp.pulsai.me"},
    )
    calls = []

    def fake_get(_db, user_id, provider, requested_tenant):
        assert user_id == user.id
        assert requested_tenant == tenant_id
        return token if provider == "pulsai" else None

    class FakeClient:
        def call_tool(self, endpoint, tool_name, arguments):
            calls.append((endpoint, tool_name, arguments))
            return {
                "data_status": "complete",
                "activities": [
                    {
                        "activity_id": "garmin-123",
                        "activity_type": "running",
                        "name": "Morning Run",
                        "start_time_utc": "2026-08-01T11:00:00Z",
                        "duration_seconds": 3600,
                        "distance_m": 10000,
                        "device": "Garmin Fenix",
                    }
                ],
            }

    monkeypatch.setattr(pulsai, "get_user_provider_token", fake_get)
    monkeypatch.setattr(
        pulsai,
        "decrypt_user_tokens",
        lambda _token: {"access_token": "https://mcp.pulsai.me/private/opaque"},
    )
    monkeypatch.setattr(pulsai.PulsaiProvider, "client_factory", FakeClient)

    provider = pulsai.PulsaiProvider()
    first = provider.fetch_activities("", db=db, user=user)
    second = provider.fetch_activities("", db=db, user=user)

    activities = [row for row in db.items if isinstance(row, Activity)]
    sources = [row for row in db.items if isinstance(row, ActivitySource)]
    assert first.status == "completed" and second.status == "completed"
    assert len(activities) == 1
    assert len(sources) == 1
    assert sources[0].provider == "pulsai"
    assert sources[0].chosen_fields["upstream_provider"] == "garmin"
    assert sources[0].raw_payload is None
    assert calls[0][1] == "get_activities"


def test_status_never_returns_private_endpoint(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=None)
    token = SimpleNamespace(
        provider_user_id="pulsai-user",
        metadata_json={
            "endpoint_host": "mcp.pulsai.me",
            "connected_at": "2026-08-02T12:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        providers_pulsai, "get_user_provider_token", lambda *_args: token
    )
    monkeypatch.setattr(providers_pulsai, "get_sync_checkpoint", lambda *_args, **_kwargs: None)
    result = providers_pulsai.pulsai_status(user=user, db=None)
    assert result["status"] == "connected"
    assert result["endpoint_host"] == "mcp.pulsai.me"
    assert "endpoint" not in result
    assert "token" not in result
