#!/usr/bin/env python3
"""Verify the public production athlete journey with exact HTTP contracts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_USER_AGENT = "curl/8.7.1 fitness-pals-smoke/1.0"
PRODUCTION_TUNNEL_NAME = "prod-fitness-pals"
WEB_OIDC_PROVIDER_SLUG = "fitness-pals-web"
PHASE8_JOURNEYS = (
    "new_athlete",
    "returning_athlete",
    "workout_analysis",
    "training_decision",
    "broken_connection",
    "failed_job",
    "mobile",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose redirect responses so login checks can validate their destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        del req, fp, code, msg, headers, newurl
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())
OpenUrl = Callable[..., Any]


@dataclass(frozen=True)
class Probe:
    """One exact production HTTP expectation."""

    name: str
    url: str
    expected_statuses: tuple[int, ...]
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "GET"
    expected_text: str | None = None
    expected_json: dict[str, object] | None = None
    require_json_object: bool = False
    required_json_keys: tuple[str, ...] = ()
    redirect_host: str | None = None
    route_contract: bool = False
    journeys: tuple[str, ...] = ()


def _open(request: urllib.request.Request, timeout: int):
    return _OPENER.open(request, timeout=timeout)


def _read_response(opener: OpenUrl, request: urllib.request.Request, timeout: int):
    """Return status, headers, and body for success and expected HTTP errors alike."""
    try:
        with opener(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _validate_response(
    probe: Probe,
    status: int,
    headers: Any,
    body: bytes,
) -> object | None:
    if status not in probe.expected_statuses:
        statuses = ", ".join(str(value) for value in probe.expected_statuses)
        raise ValueError(f"expected HTTP {statuses}, received {status}")

    text = body.decode("utf-8", errors="replace")
    if probe.expected_text is not None and probe.expected_text not in text:
        raise ValueError(f"expected response text {probe.expected_text!r}")

    payload: object | None = None
    if probe.expected_json is not None or probe.require_json_object:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("expected a JSON response body") from exc
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object response body")

    if probe.expected_json is not None:
        assert isinstance(payload, dict)
        for key, value in probe.expected_json.items():
            if payload.get(key) != value:
                raise ValueError(f"expected JSON field {key}={value!r}")

    if probe.required_json_keys:
        if not isinstance(payload, dict):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("expected a JSON response body") from exc
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object response body")
        for key in probe.required_json_keys:
            if key not in payload:
                raise ValueError(f"expected JSON field {key!r}")

    if probe.redirect_host is not None:
        location = headers.get("Location") if headers is not None else None
        if not location:
            raise ValueError("expected a redirect Location header")
        actual_host = urllib.parse.urlparse(location).hostname
        if actual_host != probe.redirect_host:
            raise ValueError(
                f"expected redirect host {probe.redirect_host!r}, received {actual_host!r}"
            )

    return payload


def verify_probe(
    probe: Probe,
    *,
    timeout_seconds: int,
    retry_interval_seconds: float = 2,
    request_timeout_seconds: int = 15,
    opener: OpenUrl = _open,
) -> object | None:
    """Retry a semantic production probe until it passes or its deadline expires."""
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            headers = {"User-Agent": DEFAULT_USER_AGENT, **probe.headers}
            request = urllib.request.Request(
                probe.url,
                headers=headers,
                method=probe.method,
            )
            status, response_headers, body = _read_response(
                opener, request, request_timeout_seconds
            )
            payload = _validate_response(probe, status, response_headers, body)
            print(f"PASS {probe.name}: HTTP {status} {probe.url}")
            return payload
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
        if time.time() >= deadline:
            break
        time.sleep(retry_interval_seconds)

    raise SystemExit(f"{probe.name} failed for {probe.url}: {last_error}")


def login_probe(
    web_base_url: str,
    auth_base_url: str = "https://auth.fitness-pals.com",
) -> Probe:
    """Return the login-entry redirect contract."""
    return Probe(
        name="login redirect",
        url=f"{web_base_url.rstrip('/')}/auth/login?next=%2Ftoday",
        expected_statuses=(302, 303, 307, 308),
        redirect_host=urllib.parse.urlparse(auth_base_url).hostname,
        journeys=("returning_athlete",),
    )


def production_probes(
    *,
    expected_release: str,
    auth_token: str,
    web_base_url: str = "https://fitness-pals.com",
    api_base_url: str = "https://api.fitness-pals.com",
    grafana_base_url: str = "https://grafana.fitness-pals.com",
    training_base_url: str = "https://training-api-prod.fitness-pals.com",
    auth_base_url: str = "https://auth.fitness-pals.com",
) -> list[Probe]:
    """Build the mandatory public production contract."""
    web = web_base_url.rstrip("/")
    api = api_base_url.rstrip("/")
    grafana = grafana_base_url.rstrip("/")
    training = training_base_url.rstrip("/")
    auth = auth_base_url.rstrip("/")
    expected_issuer = f"{auth}/application/o/{WEB_OIDC_PROVIDER_SLUG}/"
    return [
        Probe(
            name=f"Authentik readiness (expected tunnel {PRODUCTION_TUNNEL_NAME})",
            url=f"{auth}/-/health/ready/",
            expected_statuses=(200,),
            route_contract=True,
        ),
        Probe(
            name=f"Authentik OIDC discovery (expected tunnel {PRODUCTION_TUNNEL_NAME})",
            url=f"{expected_issuer}.well-known/openid-configuration",
            expected_statuses=(200,),
            expected_json={"issuer": expected_issuer},
            route_contract=True,
        ),
        Probe(
            name=f"backend readiness (expected tunnel {PRODUCTION_TUNNEL_NAME})",
            url=f"{api}/ready",
            expected_statuses=(200,),
            expected_json={"status": "ok"},
            route_contract=True,
        ),
        Probe(
            name="public front door",
            url=f"{web}/",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("new_athlete",),
        ),
        login_probe(web, auth_base_url),
        Probe(
            name="activation page route",
            url=f"{web}/welcome",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("new_athlete",),
        ),
        Probe(
            name="unauthenticated session",
            url=f"{web}/api/auth/session",
            expected_statuses=(401,),
            expected_json={"detail": "Credentials missing"},
        ),
        Probe(
            name="unauthenticated Athlete State",
            url=f"{web}/api/athlete-state?days=14",
            expected_statuses=(401,),
            expected_json={"detail": "Credentials missing"},
        ),
        Probe(
            name="API health",
            url=f"{web}/api/health-check",
            expected_statuses=(200,),
            expected_json={"status": "ok"},
        ),
        Probe(
            name="deployed release",
            url=f"{web}/deploy-version",
            expected_statuses=(200,),
            expected_text=expected_release,
        ),
        Probe(
            name="Today page route",
            url=f"{web}/today",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("returning_athlete", "training_decision"),
        ),
        Probe(
            name="Today mobile route",
            url=f"{web}/today",
            expected_statuses=(200,),
            headers={"User-Agent": "Mozilla/5.0 (iPhone; Fitness-Pals-Acceptance)"},
            route_contract=True,
            journeys=("mobile",),
        ),
        Probe(
            name="Coach page route",
            url=f"{web}/coach",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("returning_athlete", "training_decision"),
        ),
        Probe(
            name="Progress page route",
            url=f"{web}/progress",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("workout_analysis",),
        ),
        Probe(
            name="Training page route",
            url=f"{web}/training",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("workout_analysis", "failed_job"),
        ),
        Probe(
            name="Settings page route",
            url=f"{web}/settings",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("broken_connection",),
        ),
        Probe(
            name="archive recovery page route",
            url=f"{web}/import/garmin-archive",
            expected_statuses=(200,),
            route_contract=True,
            journeys=("broken_connection", "failed_job"),
        ),
        Probe(
            name="Grafana health",
            url=f"{grafana}/api/health",
            expected_statuses=(200,),
            expected_json={"database": "ok"},
        ),
        Probe(
            name="training API readiness",
            url=f"{training}/ready",
            expected_statuses=(200,),
            expected_json={"status": "ok"},
        ),
        Probe(
            name="authenticated activation state",
            url=f"{web}/api/onboarding/status",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("activation",),
            journeys=("new_athlete", "returning_athlete"),
        ),
        Probe(
            name="authenticated athlete trust state",
            url=f"{web}/api/athlete-home",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("state", "freshness"),
            journeys=("broken_connection",),
        ),
        Probe(
            name="authenticated Athlete State",
            url=f"{web}/api/athlete-state?days=14",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=(
                "source",
                "state",
                "generated_at",
                "data_through",
                "latest",
                "history",
                "training",
                "future_intent",
                "derived",
                "error",
            ),
        ),
        Probe(
            name="authenticated canonical metrics",
            url=f"{web}/api/metrics/summary",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            method="POST",
            require_json_object=True,
            required_json_keys=(
                "source",
                "state",
                "metric_states",
                "mileage",
                "hrv_avg",
                "athlete_state",
                "training",
                "future_intent",
                "error",
            ),
        ),
        Probe(
            name="authenticated archive capabilities",
            url=f"{web}/api/archive-imports/capabilities",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("drive", "upload", "latest_job"),
            journeys=("broken_connection", "failed_job"),
        ),
        Probe(
            name="authenticated athlete intelligence",
            url=f"{web}/api/intelligence",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=(
                "briefing",
                "trajectory",
                "future_intent",
                "associations",
                "preferences",
            ),
        ),
        Probe(
            name="authenticated Today decision context",
            url=f"{web}/api/today-plan/context",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("week", "trajectory", "future_intent", "match"),
            journeys=("training_decision",),
        ),
        Probe(
            name="authenticated Coach thread index",
            url=f"{web}/api/chat/threads",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("threads",),
        ),
        Probe(
            name="authenticated bounded Progress evidence",
            url=(
                f"{web}/api/journey?window=30d&sport=all&goal=all"
                "&activity_page=1&activity_page_size=25"
            ),
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=(
                "totals",
                "whole_training",
                "future_intent",
                "intent_relationship",
                "comparison",
                "activities",
                "activity_pagination",
            ),
            journeys=("workout_analysis",),
        ),
    ]



def _require_dict(value: object | None, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _validate_athlete_state_acceptance(
    payloads: dict[str, object | None],
) -> None:
    """Cross-check canonical recovery semantics across production consumers."""
    state = _require_dict(
        payloads.get("authenticated Athlete State"),
        "Athlete State",
    )
    home = _require_dict(
        payloads.get("authenticated athlete trust state"),
        "athlete-home",
    )
    metrics = _require_dict(
        payloads.get("authenticated canonical metrics"),
        "canonical metrics",
    )

    if state.get("source") != "canonical_postgres":
        raise ValueError("Athlete State must come from canonical_postgres")
    if state.get("error") is not None:
        raise ValueError("Athlete State returned an error")

    latest = state.get("latest")
    signals: dict[str, Any] | None = None
    if latest is not None:
        latest_state = _require_dict(latest, "Athlete State latest")
        signals = _require_dict(latest_state.get("signals"), "Athlete State signals")
        for signal_name in (
            "sleep_duration",
            "sleep_score",
            "overnight_hrv",
            "resting_heart_rate",
        ):
            signal = _require_dict(
                signals.get(signal_name),
                f"Athlete State signal {signal_name}",
            )
            value = signal.get("value")
            status = signal.get("status")
            if value is None and status != "unavailable":
                raise ValueError(
                    f"{signal_name} missing value must remain unavailable, got {status!r}"
                )
            if value is not None and status not in {"known", "stale"}:
                raise ValueError(
                    f"{signal_name} known value must be known/stale, got {status!r}"
                )
            provenance = _require_dict(
                signal.get("provenance"),
                f"Athlete State provenance {signal_name}",
            )
            if provenance.get("canonical_model") != "sleep_session":
                raise ValueError(
                    f"{signal_name} provenance must identify canonical sleep_session"
                )

    recovery = _require_dict(home.get("recovery"), "athlete-home recovery")
    expected_recovery = {
        "sleep_hours": None if signals is None else signals["sleep_duration"].get("value"),
        "sleep_score": None if signals is None else signals["sleep_score"].get("value"),
        "overnight_hrv": None if signals is None else signals["overnight_hrv"].get("value"),
    }
    for key, expected in expected_recovery.items():
        if recovery.get(key) != expected:
            raise ValueError(
                f"athlete-home {key} contradicts Athlete State: "
                f"{recovery.get(key)!r} != {expected!r}"
            )
    if recovery.get("state") != state.get("state"):
        raise ValueError(
            "athlete-home recovery state contradicts canonical Athlete State"
        )

    if metrics.get("source") != "canonical_postgres":
        raise ValueError("canonical metrics must come from canonical_postgres")
    if metrics.get("error") is not None:
        raise ValueError("canonical metrics returned an error")
    for key in ("mileage", "average_weekly_mileage", "long_run_max"):
        if key not in metrics:
            raise ValueError(f"canonical activity metric {key!r} is missing")

    metrics_state = _require_dict(metrics.get("athlete_state"), "metrics Athlete State")
    metrics_latest = metrics_state.get("latest")
    if latest is None:
        if metrics_latest is not None:
            raise ValueError("metrics Athlete State contradicts missing latest recovery")
    else:
        metrics_latest_state = _require_dict(metrics_latest, "metrics latest Athlete State")
        metrics_signals = _require_dict(
            metrics_latest_state.get("signals"),
            "metrics Athlete State signals",
        )
        assert signals is not None
        for signal_name in ("sleep_duration", "sleep_score", "overnight_hrv"):
            metrics_signal = _require_dict(
                metrics_signals.get(signal_name),
                f"metrics signal {signal_name}",
            )
            if metrics_signal.get("value") != signals[signal_name].get("value"):
                raise ValueError(
                    f"canonical metrics {signal_name} contradicts Athlete State"
                )

    training = _require_dict(state.get("training"), "Athlete State training")
    if training.get("state") not in {"fresh", "stale", "unknown"}:
        raise ValueError("Athlete State training must expose a trustworthy freshness state")
    modalities = training.get("by_modality")
    if not isinstance(modalities, list):
        raise ValueError("Athlete State training by_modality must be a list")
    for item in modalities:
        modality = _require_dict(item, "training modality")
        if not isinstance(modality.get("activity_count"), int):
            raise ValueError("training modality activity_count must be explicit")
        duration = modality.get("duration_seconds")
        known_duration_count = modality.get("known_duration_count")
        if known_duration_count == 0 and duration is not None:
            raise ValueError("missing training duration must remain unavailable")

    metrics_training = _require_dict(metrics.get("training"), "metrics training")
    if metrics_training != training:
        raise ValueError("canonical metrics training contradicts Athlete State training")

    journey = _require_dict(
        payloads.get("authenticated bounded Progress evidence"),
        "Progress evidence",
    )
    journey_training = _require_dict(
        journey.get("whole_training"),
        "Progress whole-training summary",
    )
    if journey_training.get("activity_count") is None:
        raise ValueError("Progress whole-training summary must expose activity_count")

    derived = _require_dict(state.get("derived"), "Athlete State derived")
    hrv = _require_dict(derived.get("hrv_7d_average"), "Athlete State HRV average")
    if metrics.get("hrv_avg") != hrv.get("value"):
        raise ValueError("canonical metrics hrv_avg contradicts Athlete State")
    metric_states = _require_dict(metrics.get("metric_states"), "metric states")
    expected_hrv_state = {
        "known": "fresh",
        "stale": "stale",
        "unavailable": "unknown",
    }.get(str(hrv.get("status") or ""), "unknown")
    if metric_states.get("hrv_avg") != expected_hrv_state:
        raise ValueError("canonical metrics HRV state contradicts Athlete State")


def _validate_future_intent_acceptance(
    payloads: dict[str, object | None],
) -> None:
    """Cross-check one canonical athlete-owned future-intent contract."""
    surfaces = {
        "Athlete State": _require_dict(
            payloads.get("authenticated Athlete State"), "Athlete State"
        ).get("future_intent"),
        "canonical metrics": _require_dict(
            payloads.get("authenticated canonical metrics"), "canonical metrics"
        ).get("future_intent"),
        "athlete intelligence": _require_dict(
            payloads.get("authenticated athlete intelligence"), "athlete intelligence"
        ).get("future_intent"),
        "Today context": _require_dict(
            payloads.get("authenticated Today decision context"), "Today context"
        ).get("future_intent"),
        "Progress": _require_dict(
            payloads.get("authenticated bounded Progress evidence"), "Progress"
        ).get("future_intent"),
    }
    future = {
        name: _require_dict(value, f"{name} future intent")
        for name, value in surfaces.items()
    }
    canonical = future["Athlete State"]
    if canonical.get("source") != "canonical_postgres":
        raise ValueError("future intent must come from canonical_postgres")
    if canonical.get("state") not in {"known", "unknown"}:
        raise ValueError("future intent must be known or unknown in production")
    if canonical.get("error") is not None:
        raise ValueError("future intent returned an error")

    canonical_intent = canonical.get("intent")

    def stable_identity(value: object | None) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            key: value.get(key)
            for key in ("goal", "target", "lifecycle", "provenance")
        }

    canonical_identity = stable_identity(canonical_intent)
    for name, surface in future.items():
        if surface.get("source") != "canonical_postgres":
            raise ValueError(f"{name} future intent source drifted")
        if surface.get("state") != canonical.get("state"):
            raise ValueError(f"{name} future intent state contradicts Athlete State")
        if stable_identity(surface.get("intent")) != canonical_identity:
            raise ValueError(f"{name} future intent contradicts Athlete State")

    if canonical.get("state") == "known":
        intent = _require_dict(canonical_intent, "canonical future intent")
        provenance = _require_dict(intent.get("provenance"), "future intent provenance")
        if provenance.get("kind") != "explicit":
            raise ValueError("future intent provenance must identify athlete-explicit input")
        if provenance.get("canonical_model") != "athlete_goal":
            raise ValueError("future intent provenance must identify athlete_goal")
        target = _require_dict(intent.get("target"), "future intent target")
        target_time = target.get("time_seconds")
        if target_time is not None and (
            isinstance(target_time, bool)
            or not isinstance(target_time, int)
            or target_time <= 0
        ):
            raise ValueError("structured target time must be positive or remain unknown")
        derived = _require_dict(intent.get("derived"), "future intent derived context")
        derived_provenance = _require_dict(
            derived.get("provenance"), "future intent derived provenance"
        )
        if derived_provenance.get("kind") != "derived":
            raise ValueError("calendar context must be labeled derived")
        caveat = str(derived.get("caveat") or "").lower()
        if "does not predict" not in caveat:
            raise ValueError("derived future intent must reject outcome prediction")
    elif canonical_intent is not None:
        raise ValueError("unknown future intent must not fabricate an intent object")

    journey = _require_dict(
        payloads.get("authenticated bounded Progress evidence"), "Progress"
    )
    relationship = _require_dict(
        journey.get("intent_relationship"), "Progress intent relationship"
    )
    expected_state = "descriptive" if canonical.get("state") == "known" else "unknown"
    if relationship.get("state") != expected_state:
        raise ValueError("Progress intent relationship state contradicts future intent")
    basis = str(relationship.get("basis") or "").lower()
    if "does not establish causation" not in basis or "does not predict" not in basis:
        raise ValueError("Progress must keep intent relationships descriptive")


def verify_production(
    *,
    expected_release: str,
    auth_token: str,
    timeout_seconds: int,
    route_timeout_seconds: int | None = None,
    retry_interval_seconds: float = 2,
    request_timeout_seconds: int = 15,
    opener: OpenUrl = _open,
    **urls: str,
) -> dict[str, object]:
    """Verify mandatory production probes and canonical Athlete State semantics."""
    if not auth_token:
        raise SystemExit("RUNTRAINER_SMOKE_AUTH_TOKEN is required")
    if route_timeout_seconds is None:
        route_timeout_seconds = timeout_seconds
    probes = production_probes(
        expected_release=expected_release,
        auth_token=auth_token,
        **urls,
    )
    passed_journeys: set[str] = set()
    payloads: dict[str, object | None] = {}
    for probe in probes:
        payloads[probe.name] = verify_probe(
            probe,
            timeout_seconds=(
                route_timeout_seconds if probe.route_contract else timeout_seconds
            ),
            retry_interval_seconds=retry_interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
            opener=opener,
        )
        passed_journeys.update(probe.journeys)

    try:
        _validate_athlete_state_acceptance(payloads)
    except ValueError as exc:
        raise SystemExit(f"Athlete State production acceptance failed: {exc}") from exc
    print("PASS Athlete State production acceptance: recovery and whole-training surfaces agree")
    try:
        _validate_future_intent_acceptance(payloads)
    except ValueError as exc:
        raise SystemExit(f"Future intent production acceptance failed: {exc}") from exc
    print("PASS future intent production acceptance: athlete-owned surfaces agree")

    missing = [journey for journey in PHASE8_JOURNEYS if journey not in passed_journeys]
    if missing:
        raise SystemExit(
            "Phase 8 acceptance report incomplete; missing journey coverage: "
            + ", ".join(missing)
        )
    report = {
        "release": expected_release,
        "status": "pass",
        "journeys": list(PHASE8_JOURNEYS),
        "probe_count": len(probes),
        "athlete_state_contract": "pass",
        "whole_training_contract": "pass",
        "future_intent_contract": "pass",
    }
    print("Production acceptance report: " + json.dumps(report, sort_keys=True))
    return report


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--route-timeout", type=int, default=30)
    parser.add_argument("--request-timeout", type=int, default=15)
    parser.add_argument("--web-base-url", default="https://fitness-pals.com")
    parser.add_argument("--api-base-url", default="https://api.fitness-pals.com")
    parser.add_argument(
        "--grafana-base-url", default="https://grafana.fitness-pals.com"
    )
    parser.add_argument(
        "--training-base-url",
        default="https://training-api-prod.fitness-pals.com",
    )
    parser.add_argument("--auth-base-url", default="https://auth.fitness-pals.com")
    args = parser.parse_args()

    verify_production(
        expected_release=args.expected_release,
        auth_token=os.environ.get("RUNTRAINER_SMOKE_AUTH_TOKEN", ""),
        timeout_seconds=args.timeout,
        route_timeout_seconds=args.route_timeout,
        request_timeout_seconds=args.request_timeout,
        web_base_url=args.web_base_url,
        api_base_url=args.api_base_url,
        grafana_base_url=args.grafana_base_url,
        training_base_url=args.training_base_url,
        auth_base_url=args.auth_base_url,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
