"""Versioned server-side bridge from Fitness-Pals to optional myChat Pal runtime."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

ADAPTER_VERSION = "fitness-pals-pal-adapter-v1"
UPSTREAM_CONTRACT_VERSION = "mychat-pal-runtime-v1"
REQUIRED_UPSTREAM_CAPABILITIES = frozenset({"session", "turn", "voice"})

PUBLIC_PERSONAS: tuple[dict[str, str], ...] = (
    {
        "persona_id": "w16-golden-glow",
        "candidate_id": "W16",
        "display_name": "Golden Glow",
        "visual_key": "W16",
        "voice_key": "w16-golden-glow-v1",
    },
    {
        "persona_id": "w18-radiant-wellness",
        "candidate_id": "W18",
        "display_name": "Radiant Wellness",
        "visual_key": "W18",
        "voice_key": "w18-radiant-wellness-v1",
    },
    {
        "persona_id": "w21-confident-coaching",
        "candidate_id": "W21",
        "display_name": "Confident Coaching",
        "visual_key": "W21",
        "voice_key": "w21-confident-coaching-v1",
    },
    {
        "persona_id": "w24-fresh-momentum",
        "candidate_id": "W24",
        "display_name": "Fresh Momentum",
        "visual_key": "W24",
        "voice_key": "w24-fresh-momentum-v1",
    },
    {
        "persona_id": "w51-tokyo-strength",
        "candidate_id": "W51",
        "display_name": "Tokyo Strength",
        "visual_key": "W51",
        "voice_key": "w51-tokyo-strength-v1",
    },
)
PERSONA_BY_ID = {item["persona_id"]: item for item in PUBLIC_PERSONAS}


class PalAdapterError(RuntimeError):
    """Base adapter error."""


class InvalidPersonaError(PalAdapterError):
    """The requested persona is not part of the canonical five-Pal cast."""


class InvalidPalSessionError(PalAdapterError):
    """The opaque adapter session is invalid, expired, or belongs to another user."""


@dataclass(frozen=True)
class PalSession:
    """Server-authenticated adapter state encoded into an opaque browser token."""

    owner_id: str
    persona_id: str
    mode: str
    issued_at: int
    upstream_session_id: str | None = None
    coach_thread_id: str | None = None
    voice_available: bool = False
    voice_text: str | None = None


@dataclass(frozen=True)
class UpstreamState:
    """Validated myChat capability snapshot."""

    available_personas: frozenset[str]
    voice_personas: frozenset[str]
    state: str
    reason: str | None = None


class PalAdapter:
    """Dark-launch adapter that never grants myChat private-profile authority."""

    def __init__(self, settings: Any, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._fernet = Fernet(str(settings.fernet_key).encode("utf-8"))
        self._client = client

    @property
    def timeout_seconds(self) -> float:
        return max(0.25, min(float(self.settings.pal_service_timeout_seconds), 5.0))

    @property
    def turn_timeout_seconds(self) -> float:
        return max(5.0, min(float(self.settings.pal_turn_timeout_seconds), 300.0))

    @property
    def voice_timeout_seconds(self) -> float:
        return max(15.0, min(float(self.settings.pal_voice_timeout_seconds), 600.0))

    @property
    def session_ttl_seconds(self) -> int:
        return max(60, min(int(self.settings.pal_session_ttl_seconds), 86400))

    def _allowed_hosts(self) -> set[str]:
        raw = str(self.settings.pal_service_allowed_hosts or "")
        return {value.strip().lower() for value in raw.split(",") if value.strip()}

    def _upstream_base_url(self) -> str | None:
        if not bool(self.settings.pal_adapter_enabled):
            return None
        value = self.settings.pal_service_url
        if value is None:
            return None
        parsed = urlparse(str(value))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        if host not in self._allowed_hosts():
            return None
        return str(value).rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Fitness-Pals-Adapter-Version": ADAPTER_VERSION,
        }
        token = str(self.settings.pal_service_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        base = self._upstream_base_url()
        if base is None:
            raise PalAdapterError("pal runtime is not configured")
        client = self._client or httpx.Client()
        close_client = self._client is None
        try:
            response = client.request(
                method,
                f"{base}{path}",
                headers=self._headers(),
                json=payload,
                timeout=timeout_seconds if timeout_seconds is not None else self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PalAdapterError("pal runtime request failed") from exc
        finally:
            if close_client:
                client.close()
        if not isinstance(body, dict):
            raise PalAdapterError("pal runtime returned a non-object payload")
        return body

    def _request_audio(
        self,
        path: str,
        *,
        payload: dict[str, Any],
    ) -> tuple[bytes, dict[str, str]]:
        base = self._upstream_base_url()
        if base is None:
            raise PalAdapterError("pal runtime is not configured")
        client = self._client or httpx.Client()
        close_client = self._client is None
        try:
            response = client.request(
                "POST",
                f"{base}{path}",
                headers=self._headers(),
                json=payload,
                timeout=self.voice_timeout_seconds,
            )
            response.raise_for_status()
            audio = response.content
            headers = {key.lower(): value for key, value in response.headers.items()}
        except httpx.HTTPError as exc:
            raise PalAdapterError("pal voice request failed") from exc
        finally:
            if close_client:
                client.close()
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "audio/wav" or not audio.startswith(b"RIFF") or len(audio) > 8_000_000:
            raise PalAdapterError("pal voice contract mismatch")
        return audio, headers

    @staticmethod
    def _validated_capabilities(body: dict[str, Any]) -> UpstreamState:
        if body.get("contract_version") != UPSTREAM_CONTRACT_VERSION:
            return UpstreamState(frozenset(), frozenset(), "degraded", "contract_version_mismatch")
        capabilities = body.get("capabilities")
        if not isinstance(capabilities, list) or not REQUIRED_UPSTREAM_CAPABILITIES.issubset(
            {value for value in capabilities if isinstance(value, str)}
        ):
            return UpstreamState(frozenset(), frozenset(), "degraded", "capability_mismatch")
        raw_personas = body.get("personas")
        if not isinstance(raw_personas, list):
            return UpstreamState(frozenset(), frozenset(), "degraded", "persona_manifest_invalid")
        available: set[str] = set()
        voice_available: set[str] = set()
        seen: set[str] = set()
        for item in raw_personas:
            if not isinstance(item, dict):
                return UpstreamState(frozenset(), frozenset(), "degraded", "persona_manifest_invalid")
            persona_id = item.get("persona_id")
            if persona_id not in PERSONA_BY_ID or persona_id in seen:
                return UpstreamState(frozenset(), frozenset(), "degraded", "persona_manifest_invalid")
            seen.add(str(persona_id))
            public = PERSONA_BY_ID[str(persona_id)]
            if item.get("voice_key") != public["voice_key"]:
                return UpstreamState(frozenset(), frozenset(), "degraded", "persona_manifest_invalid")
            if item.get("runtime_available") is True:
                available.add(str(persona_id))
                if item.get("voice_available") is True:
                    voice_available.add(str(persona_id))
        if seen != set(PERSONA_BY_ID):
            return UpstreamState(frozenset(), frozenset(), "degraded", "persona_manifest_invalid")
        return UpstreamState(
            frozenset(available),
            frozenset(voice_available),
            "ready",
            None,
        )

    def upstream_state(self) -> UpstreamState:
        if self._upstream_base_url() is None:
            return UpstreamState(frozenset(), frozenset(), "degraded", "pal_runtime_unconfigured")
        try:
            body = self._request_json("GET", "/api/pals/v1/capabilities")
        except PalAdapterError:
            return UpstreamState(frozenset(), frozenset(), "degraded", "pal_runtime_unavailable")
        return self._validated_capabilities(body)

    def discovery(self) -> dict[str, Any]:
        upstream = self.upstream_state()
        personas = [
            {
                **item,
                "runtime_available": item["persona_id"] in upstream.available_personas,
                "voice_available": item["persona_id"] in upstream.voice_personas,
            }
            for item in PUBLIC_PERSONAS
        ]
        return {
            "adapter_version": ADAPTER_VERSION,
            "upstream_contract_version": UPSTREAM_CONTRACT_VERSION,
            "state": upstream.state,
            "reason": upstream.reason,
            "personas": personas,
            "fallback": {
                "available": True,
                "mode": "coach",
                "href": "/coach",
            },
        }

    def _assert_persona(self, persona_id: str) -> None:
        if persona_id not in PERSONA_BY_ID:
            raise InvalidPersonaError("unknown Fitness-Pals persona")

    def _encode(self, session: PalSession) -> str:
        body = {
            "v": 1,
            "owner_id": session.owner_id,
            "persona_id": session.persona_id,
            "mode": session.mode,
            "issued_at": session.issued_at,
            "upstream_session_id": session.upstream_session_id,
            "coach_thread_id": session.coach_thread_id,
            "voice_available": session.voice_available,
            "voice_text": session.voice_text,
        }
        return self._fernet.encrypt(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")

    def decode_session(self, token: str, owner_id: str) -> PalSession:
        try:
            raw = self._fernet.decrypt(
                token.encode("ascii"),
                ttl=self.session_ttl_seconds,
            )
            body = json.loads(raw)
        except (InvalidToken, UnicodeError, ValueError, TypeError) as exc:
            raise InvalidPalSessionError("invalid or expired Pal session") from exc
        if not isinstance(body, dict) or body.get("v") != 1:
            raise InvalidPalSessionError("invalid Pal session version")
        if body.get("owner_id") != str(owner_id):
            raise InvalidPalSessionError("Pal session belongs to another user")
        persona_id = body.get("persona_id")
        if not isinstance(persona_id, str) or persona_id not in PERSONA_BY_ID:
            raise InvalidPalSessionError("Pal session persona is invalid")
        mode = body.get("mode")
        if mode not in {"pal", "coach-fallback"}:
            raise InvalidPalSessionError("Pal session mode is invalid")
        return PalSession(
            owner_id=str(owner_id),
            persona_id=persona_id,
            mode=mode,
            issued_at=int(body.get("issued_at") or 0),
            upstream_session_id=(
                str(body["upstream_session_id"])
                if body.get("upstream_session_id")
                else None
            ),
            coach_thread_id=(
                str(body["coach_thread_id"]) if body.get("coach_thread_id") else None
            ),
            voice_available=body.get("voice_available") is True,
            voice_text=(
                str(body["voice_text"]) if isinstance(body.get("voice_text"), str) else None
            ),
        )

    def start_session(self, owner_id: str, persona_id: str) -> tuple[PalSession, str, str | None]:
        self._assert_persona(persona_id)
        upstream = self.upstream_state()
        reason = upstream.reason
        if persona_id in upstream.available_personas:
            try:
                body = self._request_json(
                    "POST",
                    "/api/pals/v1/sessions",
                    payload={
                        "contract_version": UPSTREAM_CONTRACT_VERSION,
                        "persona_id": persona_id,
                    },
                )
                if (
                    body.get("contract_version") == UPSTREAM_CONTRACT_VERSION
                    and body.get("persona_id") == persona_id
                    and isinstance(body.get("session_id"), str)
                    and body["session_id"].strip()
                    and body.get("voice_key") == PERSONA_BY_ID[persona_id]["voice_key"]
                    and isinstance(body.get("voice_available"), bool)
                ):
                    session = PalSession(
                        owner_id=str(owner_id),
                        persona_id=persona_id,
                        mode="pal",
                        issued_at=int(time.time()),
                        upstream_session_id=body["session_id"].strip(),
                        voice_available=body.get("voice_available") is True,
                    )
                    return session, self._encode(session), None
                reason = "session_contract_mismatch"
            except PalAdapterError:
                reason = "pal_runtime_unavailable"
        session = PalSession(
            owner_id=str(owner_id),
            persona_id=persona_id,
            mode="coach-fallback",
            issued_at=int(time.time()),
        )
        return session, self._encode(session), reason or "persona_runtime_unavailable"

    def submit_upstream_turn(self, session: PalSession, message: str) -> dict[str, Any]:
        if session.mode != "pal" or not session.upstream_session_id:
            raise PalAdapterError("Pal session is not upstream-backed")
        body = self._request_json(
            "POST",
            "/api/pals/v1/turns",
            payload={
                "contract_version": UPSTREAM_CONTRACT_VERSION,
                "session_id": session.upstream_session_id,
                "persona_id": session.persona_id,
                "message": message,
            },
            timeout_seconds=self.turn_timeout_seconds,
        )
        if (
            body.get("contract_version") != UPSTREAM_CONTRACT_VERSION
            or body.get("persona_id") != session.persona_id
            or not isinstance(body.get("answer"), str)
            or not body["answer"].strip()
            or body.get("voice_key") != PERSONA_BY_ID[session.persona_id]["voice_key"]
        ):
            raise PalAdapterError("Pal turn contract mismatch")
        return {
            "answer": body["answer"].strip(),
            "persona_id": session.persona_id,
            "voice_key": PERSONA_BY_ID[session.persona_id]["voice_key"],
            "voice_available": body.get("voice_available") is True,
        }

    def bind_voice_text(
        self,
        session: PalSession,
        text: str,
        *,
        voice_available: bool,
    ) -> tuple[PalSession, str]:
        if session.mode != "pal" or not session.upstream_session_id:
            raise PalAdapterError("Pal session is not upstream-backed")
        updated = replace(
            session,
            voice_available=bool(voice_available),
            voice_text=text.strip() if voice_available and text.strip() else None,
            issued_at=int(time.time()),
        )
        return updated, self._encode(updated)

    def submit_upstream_voice(self, session: PalSession) -> tuple[bytes, str]:
        if (
            session.mode != "pal"
            or not session.upstream_session_id
            or not session.voice_available
            or not session.voice_text
        ):
            raise PalAdapterError("Pal voice is not available for this turn")
        audio, headers = self._request_audio(
            "/api/pals/v1/voice",
            payload={
                "contract_version": UPSTREAM_CONTRACT_VERSION,
                "session_id": session.upstream_session_id,
                "persona_id": session.persona_id,
                "text": session.voice_text,
            },
        )
        expected_voice = PERSONA_BY_ID[session.persona_id]["voice_key"]
        if (
            headers.get("x-mychat-contract-version") != UPSTREAM_CONTRACT_VERSION
            or headers.get("x-pal-persona-id") != session.persona_id
            or headers.get("x-pal-voice-key") != expected_voice
        ):
            raise PalAdapterError("Pal voice attribution mismatch")
        return audio, expected_voice

    def fallback_session(
        self,
        session: PalSession,
        *,
        coach_thread_id: str | None,
    ) -> tuple[PalSession, str]:
        updated = replace(
            session,
            mode="coach-fallback",
            upstream_session_id=None,
            coach_thread_id=coach_thread_id or session.coach_thread_id,
            voice_available=False,
            voice_text=None,
            issued_at=int(time.time()),
        )
        return updated, self._encode(updated)


def public_persona_ids() -> Iterable[str]:
    """Expose the canonical IDs for deterministic cross-repository contract tests."""
    return tuple(PERSONA_BY_ID)
