"""Phase 8 privacy-safe UX telemetry contracts."""

from __future__ import annotations

from types import SimpleNamespace
import uuid

from pydantic import ValidationError
import pytest

from app.routes import ux_events


def test_ux_event_schema_rejects_free_form_or_identifying_fields() -> None:
    base = {
        "event": "surface_view",
        "surface": "today",
        "viewport": "desktop",
    }
    for forbidden in ("message", "query", "user_id", "email", "activity_id", "value"):
        with pytest.raises(ValidationError):
            ux_events.UxEvent.model_validate({**base, forbidden: "sensitive"})


def test_ux_event_log_excludes_authenticated_user_identity(monkeypatch) -> None:
    captured: list[dict] = []

    def capture(_message, *, extra):
        captured.append(extra)

    monkeypatch.setattr(ux_events.logger, "info", capture)
    response = ux_events.record_ux_event(
        ux_events.UxEvent(
            event="action",
            surface="coach",
            action="ask_coach",
            state="ready",
            viewport="mobile",
        ),
        user=SimpleNamespace(id=uuid.uuid4(), email="athlete@example.com"),
    )

    assert response.status_code == 204
    assert captured == [
        {
            "ux_event": {
                "event": "action",
                "surface": "coach",
                "action": "ask_coach",
                "state": "ready",
                "viewport": "mobile",
            }
        }
    ]
    assert "user" not in str(captured).lower()
    assert "email" not in str(captured).lower()
