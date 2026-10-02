"""Deterministic contracts for Vital Presence Phase 2E Pal adapter."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.routes import pals as pal_routes
from app.routes.pals import PalSessionRequest, PalTurnRequest, PalVoiceRequest
from app.services.pal_adapter import (
    ADAPTER_VERSION,
    PREMIUM_VOICE_RENDERER,
    PUBLIC_PERSONAS,
    UPSTREAM_CONTRACT_VERSION,
    InvalidPalSessionError,
    InvalidPersonaError,
    PalAdapter,
    PalAdapterError,
)


def settings(**overrides):
    values = {
        "fernet_key": Fernet.generate_key().decode("ascii"),
        "pal_adapter_enabled": False,
        "pal_service_url": None,
        "pal_service_token": None,
        "pal_service_allowed_hosts": "",
        "pal_service_timeout_seconds": 1.0,
        "pal_turn_timeout_seconds": 180.0,
        "pal_voice_timeout_seconds": 300.0,
        "pal_session_ttl_seconds": 3600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ready_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/pals/v1/capabilities":
        return httpx.Response(
            200,
            json={
                "contract_version": UPSTREAM_CONTRACT_VERSION,
                "capabilities": ["session", "turn", "voice"],
                "personas": [
                    {
                        "persona_id": item["persona_id"],
                        "voice_key": item["voice_key"],
                        "runtime_available": True,
                        "voice_available": True,
                    }
                    for item in PUBLIC_PERSONAS
                ],
            },
        )
    if request.url.path == "/api/pals/v1/sessions":
        body = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "contract_version": UPSTREAM_CONTRACT_VERSION,
                "persona_id": body["persona_id"],
                "session_id": "private-upstream-session",
                "voice_key": next(item["voice_key"] for item in PUBLIC_PERSONAS if item["persona_id"] == body["persona_id"]),
                "voice_available": True,
                "profile_id": "must-never-leak",
            },
        )
    if request.url.path == "/api/pals/v1/turns":
        body = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "contract_version": UPSTREAM_CONTRACT_VERSION,
                "persona_id": body["persona_id"],
                "answer": "Measured response",
                "voice_key": next(item["voice_key"] for item in PUBLIC_PERSONAS if item["persona_id"] == body["persona_id"]),
                "voice_available": True,
                "memory_rows": ["must-never-leak"],
                "profile_id": "must-never-leak",
            },
        )
    if request.url.path == "/api/pals/v1/voice":
        body = __import__("json").loads(request.content)
        assert body["text"] == "Measured response"
        voice_key = next(
            item["voice_key"]
            for item in PUBLIC_PERSONAS
            if item["persona_id"] == body["persona_id"]
        )
        return httpx.Response(
            200,
            content=b"RIFF" + (b"\x00" * 256),
            headers={
                "Content-Type": "audio/wav",
                "X-MyChat-Contract-Version": UPSTREAM_CONTRACT_VERSION,
                "X-Pal-Persona-Id": body["persona_id"],
                "X-Pal-Voice-Key": voice_key,
                "X-Pal-Voice-Renderer": PREMIUM_VOICE_RENDERER,
            },
        )
    return httpx.Response(404)


def enabled_settings(**overrides):
    values = {
        "pal_adapter_enabled": True,
        "pal_service_url": "https://mychat.internal",
        "pal_service_allowed_hosts": "mychat.internal",
        "pal_service_token": "server-only-secret",
    }
    values.update(overrides)
    return settings(**values)


def test_canonical_five_pal_public_contract_matches_mychat_2d():
    assert ADAPTER_VERSION == "fitness-pals-pal-adapter-v1"
    assert [(item["candidate_id"], item["persona_id"], item["display_name"]) for item in PUBLIC_PERSONAS] == [
        ("W16", "w16-golden-glow", "Golden Glow"),
        ("W18", "w18-radiant-wellness", "Radiant Wellness"),
        ("W21", "w21-confident-coaching", "Confident Coaching"),
        ("W24", "w24-fresh-momentum", "Fresh Momentum"),
        ("W51", "w51-tokyo-strength", "Tokyo Strength"),
    ]
    assert [item["voice_key"] for item in PUBLIC_PERSONAS] == [
        "w16-golden-glow-v1",
        "w18-radiant-wellness-v1",
        "w21-confident-coaching-v1",
        "w24-fresh-momentum-v1",
        "w51-tokyo-strength-v1",
    ]


def test_unconfigured_runtime_is_truthfully_degraded_with_coach_fallback():
    discovery = PalAdapter(settings()).discovery()

    assert discovery["state"] == "degraded"
    assert discovery["reason"] == "pal_runtime_unconfigured"
    assert len(discovery["personas"]) == 5
    assert not any(item["runtime_available"] for item in discovery["personas"])
    assert discovery["fallback"] == {
        "available": True,
        "mode": "coach",
        "href": "/coach",
    }


def test_runtime_host_must_be_explicitly_allow_listed():
    adapter = PalAdapter(
        enabled_settings(pal_service_allowed_hosts="different.internal"),
        client=client(ready_handler),
    )
    discovery = adapter.discovery()

    assert discovery["state"] == "degraded"
    assert discovery["reason"] == "pal_runtime_unconfigured"


def test_contract_mismatch_never_activates_a_pal():
    def mismatch(_request):
        return httpx.Response(
            200,
            json={
                "contract_version": "future-incompatible-version",
                "capabilities": ["session", "turn"],
                "personas": [],
            },
        )

    adapter = PalAdapter(enabled_settings(), client=client(mismatch))
    discovery = adapter.discovery()

    assert discovery["state"] == "degraded"
    assert discovery["reason"] == "contract_version_mismatch"
    assert not any(item["runtime_available"] for item in discovery["personas"])


def test_unknown_persona_is_rejected_before_any_session_is_issued():
    adapter = PalAdapter(settings())

    with pytest.raises(InvalidPersonaError):
        adapter.start_session("owner", "w99-invented-pal")


def test_session_token_is_opaque_owner_bound_and_persona_bound():
    adapter = PalAdapter(settings())
    owner = str(uuid4())
    session, token, reason = adapter.start_session(owner, "w16-golden-glow")

    assert session.mode == "coach-fallback"
    assert reason == "pal_runtime_unconfigured"
    assert owner not in token
    assert "w16-golden-glow" not in token
    resolved = adapter.decode_session(token, owner)
    assert resolved.persona_id == "w16-golden-glow"
    with pytest.raises(InvalidPalSessionError):
        adapter.decode_session(token, str(uuid4()))


def test_request_models_forbid_client_profile_or_private_authority_claims():
    with pytest.raises(ValidationError):
        PalSessionRequest(persona_id="w16-golden-glow", profile_id="claimed-profile")
    with pytest.raises(ValidationError):
        PalTurnRequest(
            session_token="x" * 64,
            message="Hello",
            passkey="claimed-passkey",
        )
    with pytest.raises(ValidationError):
        PalVoiceRequest(
            session_token="x" * 64,
            text="browser-authored speech must be rejected",
        )


def test_compatible_upstream_can_start_and_return_only_allow_listed_turn_fields():
    adapter = PalAdapter(enabled_settings(), client=client(ready_handler))
    owner = str(uuid4())

    session, token, reason = adapter.start_session(owner, "w21-confident-coaching")
    assert reason is None
    assert session.mode == "pal"
    assert session.upstream_session_id == "private-upstream-session"

    turn = adapter.submit_upstream_turn(session, "What should I do?")
    assert turn == {
        "answer": "Measured response",
        "persona_id": "w21-confident-coaching",
        "voice_key": "w21-confident-coaching-v1",
        "voice_available": True,
    }
    assert "profile_id" not in turn
    assert "memory_rows" not in turn
    assert session.voice_available is True

    _bound, voice_token = adapter.bind_voice_text(
        session,
        turn["answer"],
        voice_available=turn["voice_available"],
    )
    resolved = adapter.decode_session(voice_token, owner)
    assert resolved.voice_text == "Measured response"
    audio, voice_key, voice_renderer = adapter.submit_upstream_voice(resolved)
    assert audio.startswith(b"RIFF")
    assert voice_key == "w21-confident-coaching-v1"
    assert voice_renderer == PREMIUM_VOICE_RENDERER
    assert adapter.decode_session(token, owner).mode == "pal"


def test_transient_voice_503_retries_once_and_recovers(monkeypatch):
    attempts = {"voice": 0}

    def transient(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pals/v1/voice":
            attempts["voice"] += 1
            if attempts["voice"] == 1:
                return httpx.Response(
                    503,
                    json={
                        "contract_version": UPSTREAM_CONTRACT_VERSION,
                        "error": "voice_render_failed",
                    },
                )
        return ready_handler(request)

    monkeypatch.setattr("app.services.pal_adapter.time.sleep", lambda _seconds: None)
    adapter = PalAdapter(enabled_settings(), client=client(transient))
    owner = str(uuid4())
    session, _token, reason = adapter.start_session(owner, "w16-golden-glow")
    assert reason is None
    turn = adapter.submit_upstream_turn(session, "Recovery?")
    resolved, _voice_token = adapter.bind_voice_text(
        session,
        turn["answer"],
        voice_available=turn["voice_available"],
    )

    audio, voice_key, voice_renderer = adapter.submit_upstream_voice(resolved)

    assert attempts["voice"] == 2
    assert audio.startswith(b"RIFF")
    assert voice_key == "w16-golden-glow-v1"
    assert voice_renderer == PREMIUM_VOICE_RENDERER


def test_non_premium_voice_renderer_is_rejected():
    def degraded_renderer(request: httpx.Request) -> httpx.Response:
        response = ready_handler(request)
        if request.url.path != "/api/pals/v1/voice":
            return response
        headers = dict(response.headers)
        headers["X-Pal-Voice-Renderer"] = "legacy-or-fallback-renderer"
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=headers,
        )

    adapter = PalAdapter(enabled_settings(), client=client(degraded_renderer))
    owner = str(uuid4())
    session, _token, reason = adapter.start_session(owner, "w18-radiant-wellness")
    assert reason is None
    turn = adapter.submit_upstream_turn(session, "Recovery?")
    resolved, _voice_token = adapter.bind_voice_text(
        session,
        turn["answer"],
        voice_available=turn["voice_available"],
    )

    with pytest.raises(PalAdapterError, match="voice attribution mismatch"):
        adapter.submit_upstream_voice(resolved)


def test_persistent_voice_503_stops_after_one_retry(monkeypatch):
    attempts = {"voice": 0}

    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pals/v1/voice":
            attempts["voice"] += 1
            return httpx.Response(
                503,
                json={
                    "contract_version": UPSTREAM_CONTRACT_VERSION,
                    "error": "voice_render_failed",
                },
            )
        return ready_handler(request)

    monkeypatch.setattr("app.services.pal_adapter.time.sleep", lambda _seconds: None)
    adapter = PalAdapter(enabled_settings(), client=client(unavailable))
    owner = str(uuid4())
    session, _token, reason = adapter.start_session(owner, "w16-golden-glow")
    assert reason is None
    turn = adapter.submit_upstream_turn(session, "Recovery?")
    resolved, _voice_token = adapter.bind_voice_text(
        session,
        turn["answer"],
        voice_available=turn["voice_available"],
    )

    with pytest.raises(PalAdapterError, match="voice_render_failed"):
        adapter.submit_upstream_voice(resolved)

    assert attempts["voice"] == 2


def test_timeout_degrades_to_coach_fallback_without_losing_session_creation():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    adapter = PalAdapter(enabled_settings(), client=client(timeout))
    session, token, reason = adapter.start_session(
        str(uuid4()), "w24-fresh-momentum"
    )

    assert session.mode == "coach-fallback"
    assert token
    assert reason == "pal_runtime_unavailable"


def test_route_fallback_reuses_durable_coach_and_rotates_thread_into_session(monkeypatch):
    adapter = PalAdapter(settings())
    owner = str(uuid4())
    _session, token, _reason = adapter.start_session(owner, "w51-tokyo-strength")
    thread_id = str(uuid4())

    calls = []

    def fake_coach(request, *, user, db):
        calls.append((request, user, db))
        return {
            "turn": {"id": str(uuid4()), "status": "success", "answer": "Coach answer"},
            "thread": {"id": thread_id, "turns": []},
        }

    monkeypatch.setattr(pal_routes, "coach_chat", fake_coach)
    user = SimpleNamespace(id=owner)

    result = pal_routes.submit_pal_turn(
        PalTurnRequest(session_token=token, message="Keep this question"),
        user=user,
        db=object(),
        adapter=adapter,
    )

    assert result["mode"] == "coach-fallback"
    assert result["speaker"] == "Coach"
    assert result["answer"] == "Coach answer"
    assert result["active_persona_id"] is None
    assert result["fallback"]["href"] == "/coach"
    assert len(calls) == 1
    assert calls[0][0].message == "Keep this question"
    resolved = adapter.decode_session(result["session_token"], owner)
    assert resolved.coach_thread_id == thread_id
