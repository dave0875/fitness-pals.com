"""Tests for semantic public production smoke checks."""

from __future__ import annotations

import copy
import io
import json
import urllib.error
from http.client import HTTPMessage
from typing import Literal

import pytest

from scripts import smoke_production


class FakeResponse:
    """Small context-manager response used by production smoke tests."""

    def __init__(
        self,
        status: int,
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        if isinstance(body, bytes):
            self._body = body
        elif isinstance(body, str):
            self._body = body.encode()
        else:
            self._body = json.dumps(body or {}).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def read(self) -> bytes:
        return self._body

    def __exit__(self, exc_type, exc, traceback) -> Literal[False]:
        del exc_type, exc, traceback
        return False


def http_error(url: str, status: int, body: object = None) -> urllib.error.HTTPError:
    payload = json.dumps(body or {}).encode()
    return urllib.error.HTTPError(
        url,
        status,
        "expected test response",
        HTTPMessage(),
        io.BytesIO(payload),
    )



def future_intent_payload() -> dict[str, object]:
    return {
        "source": "canonical_postgres",
        "state": "known",
        "generated_at": "2026-09-24T12:00:00+00:00",
        "intent": {
            "goal": {
                "type": "marathon",
                "label": "Marathon",
                "phase": "build",
                "phase_label": "Training / build",
                "custom": None,
            },
            "target": {
                "date": "2026-11-01",
                "distance": "Marathon",
                "performance": "3:15",
                "time_seconds": None,
            },
            "lifecycle": {
                "state": "current",
                "created_at": "2026-09-01T12:00:00+00:00",
                "updated_at": "2026-09-23T12:00:00+00:00",
                "ended_at": None,
            },
            "provenance": {
                "kind": "explicit",
                "source": "onboarding",
                "canonical_model": "athlete_goal",
                "record_id": "goal-1",
                "explicit_fields": [
                    "goal.type",
                    "goal.phase",
                    "target.date",
                    "target.distance",
                    "target.performance",
                ],
            },
            "derived": {
                "days_to_target": 38,
                "target_date_relation": "future",
                "provenance": {
                    "kind": "derived",
                    "basis": ["target.date", "generated_at"],
                },
                "caveat": (
                    "Calendar relationship only. It does not predict finish time, "
                    "readiness, or race outcome."
                ),
            },
        },
        "error": None,
    }


def goal_graph_payload() -> dict[str, object]:
    return {
        "source": "canonical_postgres",
        "state": "known",
        "generated_at": "2026-09-24T12:00:00+00:00",
        "goal": {
            "type": "marathon",
            "label": "Marathon",
            "phase": "build",
            "phase_label": "Training / build",
            "target_date": "2026-11-01",
        },
        "primary_event": {
            "id": "event-1",
            "role": "primary",
            "type": "marathon",
            "label": "NYC Marathon",
            "date": "2026-11-01",
            "distance": "Marathon",
            "target_performance": "3:15",
            "target_time_seconds": None,
            "priority": 1,
            "lifecycle": {"state": "planned", "created_at": None, "updated_at": None},
            "provenance": {
                "kind": "explicit",
                "source": "goal_graph",
                "canonical_model": "athlete_goal_event",
                "record_id": "event-1",
                "explicit_fields": ["event.role", "event.type", "event.date"],
            },
            "derived": {
                "days_to_event": 38,
                "date_relation": "future",
                "provenance": {"kind": "derived", "basis": ["event.date", "generated_at"]},
                "caveat": (
                    "Calendar relationship only. It does not predict finish time, "
                    "readiness, or race outcome."
                ),
            },
        },
        "supporting_events": [],
        "calendar": [],
        "events": [],
        "objectives": [],
        "truncated": {"events": False, "objectives": False},
        "error": None,
    }


def decision_payload() -> dict[str, object]:
    return {
        "source": "canonical_postgres",
        "version": "athlete_orbit_v1",
        "state": "caution",
        "generated_at": "2026-09-24T12:00:00+00:00",
        "action": {
            "code": "conservative_goal_session",
            "label": "Keep the next goal-aligned session conservative",
            "href": "/today#todays-run",
            "priority": "recovery",
            "training_bias": "conservative",
        },
        "freshness": {
            "state": "partial",
            "recovery": "stale",
            "training": "fresh",
        },
        "rationale": [
            {
                "code": "goal_anchor",
                "summary": "The canonical Goal Graph anchors this decision.",
            }
        ],
        "uncertainty": [
            {
                "code": "recovery_stale",
                "summary": (
                    "Recovery evidence is stale and is not used as proof "
                    "of current readiness."
                ),
            }
        ],
        "conflicts": [],
        "evidence": {
            "goal": {
                "state": "known",
                "goal_type": "marathon",
                "phase": "build",
                "primary_event": {
                    "id": "event-1",
                    "type": "marathon",
                    "label": "NYC Marathon",
                    "date": "2026-11-01",
                    "days_to_event": 38,
                    "priority": 1,
                },
                "supporting_event_count": 0,
                "objective_count": 0,
            },
            "recovery": {
                "state": "stale",
                "data_through": "2026-09-20",
                "known_signals": [
                    "overnight_hrv",
                    "sleep_duration",
                    "sleep_score",
                ],
                "stale_signals": [
                    "overnight_hrv",
                    "sleep_duration",
                    "sleep_score",
                ],
                "unavailable_signals": ["resting_heart_rate"],
            },
            "training": {
                "state": "fresh",
                "data_through": "2026-09-24T10:00:00+00:00",
                "window_days": 30,
                "activity_count": 3,
                "duration_seconds": 9000,
                "known_duration_count": 3,
                "by_modality": [
                    {
                        "modality": "running",
                        "activity_count": 2,
                        "duration_seconds": 6000,
                        "known_duration_count": 2,
                    },
                    {
                        "modality": "strength",
                        "activity_count": 1,
                        "duration_seconds": 3000,
                        "known_duration_count": 1,
                    },
                ],
                "cross_training_sessions": 1,
                "strength_sessions": 1,
            },
        },
        "provenance": {
            "kind": "derived",
            "basis": [
                "athlete_goal_graph",
                "athlete_state_recovery",
                "whole_training_summary",
            ],
            "caveat": (
                "Decision support only. It does not establish medical readiness, "
                "diagnose a condition, or predict a race outcome."
            ),
        },
        "error": None,
    }


def athlete_state_payload() -> dict[str, object]:
    provenance = {
        "canonical_model": "sleep_session",
        "record_id": "sleep-1",
        "provider": "garmin",
        "provider_record_id": "20260920",
        "ingest_run_id": None,
    }
    signals = {
        "sleep_duration": {
            "value": 7.0,
            "unit": "hours",
            "status": "stale",
            "observation_date": "2026-09-20",
            "stale_after": "2026-09-23T23:59:59+00:00",
            "provenance": provenance,
        },
        "sleep_score": {
            "value": 78,
            "unit": "score",
            "status": "stale",
            "observation_date": "2026-09-20",
            "stale_after": "2026-09-23T23:59:59+00:00",
            "provenance": provenance,
        },
        "overnight_hrv": {
            "value": 41,
            "unit": "ms",
            "status": "stale",
            "observation_date": "2026-09-20",
            "stale_after": "2026-09-23T23:59:59+00:00",
            "provenance": provenance,
        },
        "resting_heart_rate": {
            "value": None,
            "unit": "bpm",
            "status": "unavailable",
            "observation_date": "2026-09-20",
            "stale_after": "2026-09-23T23:59:59+00:00",
            "provenance": provenance,
        },
    }
    latest = {
        "date": "2026-09-20",
        "state": "stale",
        "data_through": "2026-09-20",
        "signals": signals,
    }
    training = {
        "state": "fresh",
        "data_through": "2026-09-24T10:00:00+00:00",
        "window_days": 30,
        "activity_count": 3,
        "duration_seconds": 9000,
        "known_duration_count": 3,
        "by_modality": [
            {
                "modality": "running",
                "activity_count": 2,
                "duration_seconds": 6000,
                "known_duration_count": 2,
            },
            {
                "modality": "strength",
                "activity_count": 1,
                "duration_seconds": 3000,
                "known_duration_count": 1,
            },
        ],
        "cross_training_sessions": 1,
        "strength_sessions": 1,
        "hr_supported_workouts": 2,
        "hr_supported_duration_seconds": 6000,
        "power_supported_cycling_workouts": 0,
        "power_supported_cycling_duration_seconds": None,
    }
    return {
        "source": "canonical_postgres",
        "state": "stale",
        "generated_at": "2026-09-24T12:00:00+00:00",
        "data_through": "2026-09-20",
        "latest": latest,
        "history": [latest],
        "training": training,
        "future_intent": future_intent_payload(),
        "goal_graph": goal_graph_payload(),
        "decision": decision_payload(),
        "derived": {
            "hrv_7d_average": {
                "value": 41,
                "unit": "ms",
                "status": "stale",
                "window_days": 7,
                "sample_count": 1,
            }
        },
        "error": None,
    }


def athlete_home_payload() -> dict[str, object]:
    return {
        "state": "ready",
        "freshness": {
            "state": "partial",
            "signals": {
                "activities": {"state": "fresh"},
                "sleep": {"state": "stale"},
            },
        },
        "recovery": {
            "state": "stale",
            "label": "Recovery data is stale",
            "sleep_hours": 7.0,
            "sleep_score": 78,
            "overnight_hrv": 41,
        },
        "decision": decision_payload(),
    }


def metrics_payload(state: dict[str, object]) -> dict[str, object]:
    return {
        "source": "canonical_postgres",
        "state": "fresh",
        "metric_states": {
            "mileage": "fresh",
            "average_weekly_mileage": "fresh",
            "long_run_max": "fresh",
            "hrv_avg": "stale",
            "pace_histogram": "unknown",
            "training_load": "unknown",
        },
        "mileage": {"30d": 100000, "60d": 200000, "90d": 300000},
        "average_weekly_mileage": 25000,
        "long_run_max": 30000,
        "hrv_avg": 41,
        "athlete_state": state,
        "training": state["training"],
        "future_intent": state["future_intent"],
        "goal_graph": state["goal_graph"],
        "decision": state["decision"],
        "error": None,
    }


def test_production_smoke_proves_public_and_authenticated_contracts() -> None:
    token = "short-lived-token"
    release = "abc123"
    seen: list[tuple[str, str | None]] = []
    state = athlete_state_payload()

    def opener(request, timeout):
        del timeout
        url = request.full_url
        authorization = request.headers.get("Authorization")
        seen.append((url, authorization))
        if url.endswith("/auth/login?next=%2Ftoday"):
            return FakeResponse(
                302,
                headers={
                    "Location": "https://auth.fitness-pals.com/application/o/authorize/"
                },
            )
        if url == "https://fitness-pals.com/" or any(
            url.endswith(route)
            for route in (
                "/welcome",
                "/today",
                "/coach",
                "/progress",
                "/training",
                "/settings",
                "/import/garmin-archive",
            )
        ):
            return FakeResponse(
                200,
                '<html>Fitness Pals <section data-contract="athlete-orbit-story-v1"></section></html>',
            )
        if url.endswith("/api/auth/session"):
            raise http_error(url, 401, {"detail": "Credentials missing"})
        if url.endswith("/api/athlete-state?days=14"):
            if authorization is None:
                raise http_error(url, 401, {"detail": "Credentials missing"})
            assert authorization == f"Bearer {token}"
            return FakeResponse(200, state)
        if url.endswith("/api/health-check"):
            return FakeResponse(200, {"status": "ok"})
        if url.endswith("/-/health/ready/"):
            return FakeResponse(200, "ok")
        if url.endswith("/.well-known/openid-configuration"):
            return FakeResponse(
                200,
                {
                    "issuer": (
                        "https://auth.fitness-pals.com/application/o/"
                        "fitness-pals-web/"
                    )
                },
            )
        if url.endswith("/ready"):
            return FakeResponse(200, {"status": "ok"})
        if url.endswith("/deploy-version"):
            return FakeResponse(200, f"release {release}")
        if url.endswith("/api/health"):
            return FakeResponse(200, {"database": "ok", "version": "1"})
        if url.endswith("/api/onboarding/status"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(
                200,
                {
                    "activation": {
                        "state": "fully_usable",
                        "requires_activation": False,
                        "usable_now": True,
                    }
                },
            )
        if url.endswith("/api/athlete-home"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(200, athlete_home_payload())
        if url.endswith("/api/metrics/summary"):
            assert authorization == f"Bearer {token}"
            assert request.get_method() == "POST"
            return FakeResponse(200, metrics_payload(state))
        if url.endswith("/api/archive-imports/capabilities"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(
                200,
                {
                    "drive": {"available": True},
                    "upload": {"available": True},
                    "latest_job": None,
                },
            )
        if url.endswith("/api/intelligence"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(
                200,
                {
                    "briefing": {"state": "available"},
                    "trajectory": {"interpretation": "Inputs only"},
                    "future_intent": state["future_intent"],
                    "goal_graph": state["goal_graph"],
                    "decision": state["decision"],
                    "associations": [],
                    "preferences": [],
                },
            )
        if url.endswith("/api/today-plan/context"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(
                200,
                {
                    "week": {"days": []},
                    "trajectory": {},
                    "future_intent": state["future_intent"],
                    "goal_graph": state["goal_graph"],
                    "decision": state["decision"],
                    "match": None,
                },
            )
        if url.endswith("/api/chat/threads"):
            assert authorization == f"Bearer {token}"
            return FakeResponse(200, {"threads": []})
        if "/api/journey?" in url:
            assert authorization == f"Bearer {token}"
            return FakeResponse(
                200,
                {
                    "totals": {"activity_count": 0},
                    "future_intent": state["future_intent"],
                    "goal_graph": state["goal_graph"],
                    "decision": state["decision"],
                    "intent_relationship": {
                        "state": "descriptive",
                        "observed_activity_count": 0,
                        "observed_duration_seconds": 0,
                        "goal_type": "marathon",
                        "target_date": "2026-11-01",
                        "basis": (
                            "Observed canonical training is displayed beside current "
                            "explicit intent. This does not establish causation and "
                            "does not predict a race or event outcome."
                        ),
                    },
                    "whole_training": {
                        "activity_count": 0,
                        "duration_seconds": None,
                        "known_duration_count": 0,
                        "by_modality": [],
                        "cross_training_sessions": 0,
                        "strength_sessions": 0,
                        "hr_supported_workouts": 0,
                        "hr_supported_duration_seconds": None,
                        "power_supported_cycling_workouts": 0,
                        "power_supported_cycling_duration_seconds": None,
                    },
                    "comparison": {"state": "available"},
                    "activities": [],
                    "activity_pagination": {
                        "page": 1,
                        "page_size": 25,
                        "total_items": 0,
                        "total_pages": 1,
                        "from": 0,
                        "to": 0,
                    },
                },
            )
        raise AssertionError(f"unexpected URL {url}")

    report = smoke_production.verify_production(
        expected_release=release,
        auth_token=token,
        timeout_seconds=1,
        route_timeout_seconds=1,
        retry_interval_seconds=0,
        opener=opener,
    )

    assert len(seen) == 28
    assert sum(authorization is not None for _, authorization in seen) == 9
    assert report == {
        "release": release,
        "status": "pass",
        "journeys": list(smoke_production.PHASE8_JOURNEYS),
        "probe_count": 28,
        "athlete_state_contract": "pass",
        "whole_training_contract": "pass",
        "future_intent_contract": "pass",
        "goal_graph_contract": "pass",
        "decision_contract": "pass",
        "experience_contract": "pass",
    }
    assert any(url.endswith("/api/onboarding/status") for url, _ in seen)
    assert any(url.endswith("/api/athlete-home") for url, _ in seen)
    assert sum(url.endswith("/api/athlete-state?days=14") for url, _ in seen) == 2
    assert any(url.endswith("/api/metrics/summary") for url, _ in seen)
    assert any(url.endswith("/api/archive-imports/capabilities") for url, _ in seen)
    assert any(url.endswith("/api/intelligence") for url, _ in seen)
    assert any(url.endswith("/api/today-plan/context") for url, _ in seen)
    assert any(url.endswith("/api/chat/threads") for url, _ in seen)
    assert any(
        "/api/journey?window=30d&sport=all&goal=all"
        "&activity_page=1&activity_page_size=25" in url
        for url, _ in seen
    )



def test_future_intent_acceptance_rejects_invalid_structured_target_time() -> None:
    state = athlete_state_payload()
    future = copy.deepcopy(state["future_intent"])
    assert isinstance(future, dict)
    intent = future["intent"]
    assert isinstance(intent, dict)
    target = intent["target"]
    assert isinstance(target, dict)
    target["time_seconds"] = -1

    invalid_state = copy.deepcopy(state)
    invalid_state["future_intent"] = future
    payloads = {
        "authenticated Athlete State": invalid_state,
        "authenticated canonical metrics": {
            **metrics_payload(state),
            "future_intent": future,
        },
        "authenticated athlete intelligence": {"future_intent": future},
        "authenticated Today decision context": {"future_intent": future},
        "authenticated bounded Progress evidence": {
            "future_intent": future,
            "intent_relationship": {
                "state": "descriptive",
                "basis": (
                    "This does not establish causation and does not predict a race outcome."
                ),
            },
        },
    }

    with pytest.raises(ValueError, match="structured target time"):
        smoke_production._validate_future_intent_acceptance(payloads)


def test_athlete_state_acceptance_rejects_fabricated_missing_signal() -> None:
    state = athlete_state_payload()
    latest = state["latest"]
    assert isinstance(latest, dict)
    signals = latest["signals"]
    assert isinstance(signals, dict)
    hrv = signals["overnight_hrv"]
    assert isinstance(hrv, dict)
    hrv["value"] = None
    hrv["status"] = "known"

    with pytest.raises(ValueError, match="missing value must remain unavailable"):
        smoke_production._validate_athlete_state_acceptance(
            {
                "authenticated Athlete State": state,
                "authenticated athlete trust state": athlete_home_payload(),
                "authenticated canonical metrics": metrics_payload(
                    athlete_state_payload()
                ),
            }
        )


def test_athlete_state_acceptance_rejects_dashboard_recovery_mismatch() -> None:
    state = athlete_state_payload()
    home = copy.deepcopy(athlete_home_payload())
    recovery = home["recovery"]
    assert isinstance(recovery, dict)
    recovery["overnight_hrv"] = 99

    with pytest.raises(ValueError, match="contradicts Athlete State"):
        smoke_production._validate_athlete_state_acceptance(
            {
                "authenticated Athlete State": state,
                "authenticated athlete trust state": home,
                "authenticated canonical metrics": metrics_payload(state),
            }
        )


def test_production_smoke_reports_authentik_tunnel_drift_before_login() -> None:
    seen: list[str] = []

    def opener(request, timeout):
        del timeout
        seen.append(request.full_url)
        raise http_error(request.full_url, 502)

    with pytest.raises(
        SystemExit,
        match="Authentik readiness.*prod-fitness-pals.*received 502",
    ):
        smoke_production.verify_production(
            expected_release="abc123",
            auth_token="short-lived-token",
            timeout_seconds=60,
            route_timeout_seconds=0,
            retry_interval_seconds=0,
            opener=opener,
        )

    assert seen == ["https://auth.fitness-pals.com/-/health/ready/"]


def test_production_smoke_rejects_login_page_that_does_not_redirect() -> None:
    def opener(request, timeout):
        del request, timeout
        return FakeResponse(200, "login error page")

    with pytest.raises(SystemExit, match="login redirect"):
        smoke_production.verify_probe(
            smoke_production.login_probe("https://fitness-pals.com"),
            timeout_seconds=0,
            retry_interval_seconds=0,
            opener=opener,
        )


def test_production_smoke_rejects_unexpected_unauthenticated_status() -> None:
    def opener(request, timeout):
        del request, timeout
        raise http_error("https://fitness-pals.com/api/auth/session", 500)

    with pytest.raises(SystemExit, match="expected HTTP 401, received 500"):
        smoke_production.verify_probe(
            smoke_production.Probe(
                name="unauthenticated session",
                url="https://fitness-pals.com/api/auth/session",
                expected_statuses=(401,),
            ),
            timeout_seconds=0,
            retry_interval_seconds=0,
            opener=opener,
        )


def test_production_smoke_rejects_stale_release() -> None:
    def opener(request, timeout):
        del request, timeout
        return FakeResponse(200, "release old-sha")

    with pytest.raises(SystemExit, match="expected response text"):
        smoke_production.verify_probe(
            smoke_production.Probe(
                name="deployed release",
                url="https://fitness-pals.com/deploy-version",
                expected_statuses=(200,),
                expected_text="new-sha",
            ),
            timeout_seconds=0,
            retry_interval_seconds=0,
            opener=opener,
        )



def test_phase6_experience_acceptance_rejects_untraceable_surface() -> None:
    decision = decision_payload()
    provenance = decision["provenance"]
    assert isinstance(provenance, dict)
    provenance["basis"] = ["athlete_goal_graph"]

    payloads: dict[str, object | None] = {
        "authenticated athlete trust state": {"decision": decision},
        "authenticated athlete intelligence": {"decision": decision_payload()},
        "authenticated Today decision context": {"decision": decision_payload()},
        "authenticated bounded Progress evidence": {"decision": decision_payload()},
    }

    with pytest.raises(ValueError, match="provenance is not traceable"):
        smoke_production._validate_experience_acceptance(payloads)


def test_phase6_core_routes_require_visible_orbit_contract_marker() -> None:
    probes = smoke_production.production_probes(
        expected_release="abc123",
        auth_token="token",
    )
    required = {
        "Today page route",
        "Coach page route",
        "Progress page route",
    }
    selected = {probe.name: probe for probe in probes if probe.name in required}
    assert set(selected) == required
    for probe in selected.values():
        assert probe.expected_text == 'data-contract="athlete-orbit-story-v1"'
