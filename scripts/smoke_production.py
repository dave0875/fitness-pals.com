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
    expected_text: str | None = None
    expected_json: dict[str, object] | None = None
    require_json_object: bool = False
    required_json_keys: tuple[str, ...] = ()
    redirect_host: str | None = None
    route_contract: bool = False


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
) -> None:
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


def verify_probe(
    probe: Probe,
    *,
    timeout_seconds: int,
    retry_interval_seconds: float = 2,
    request_timeout_seconds: int = 15,
    opener: OpenUrl = _open,
) -> None:
    """Retry a semantic production probe until it passes or its deadline expires."""
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            headers = {"User-Agent": DEFAULT_USER_AGENT, **probe.headers}
            request = urllib.request.Request(probe.url, headers=headers)
            status, response_headers, body = _read_response(
                opener, request, request_timeout_seconds
            )
            _validate_response(probe, status, response_headers, body)
            print(f"PASS {probe.name}: HTTP {status} {probe.url}")
            return
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
        if time.time() >= deadline:
            break
        time.sleep(retry_interval_seconds)

    raise SystemExit(f"{probe.name} failed for {probe.url}: {last_error}")


def login_probe(web_base_url: str, auth_base_url: str = "https://auth.fitness-pals.com") -> Probe:
    """Return the login-entry redirect contract."""
    return Probe(
        name="login redirect",
        url=f"{web_base_url.rstrip('/')}/auth/login?next=%2Ftoday",
        expected_statuses=(302, 303, 307, 308),
        redirect_host=urllib.parse.urlparse(auth_base_url).hostname,
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
            name=(
                "Authentik readiness "
                f"(expected tunnel {PRODUCTION_TUNNEL_NAME})"
            ),
            url=f"{auth}/-/health/ready/",
            expected_statuses=(200,),
            route_contract=True,
        ),
        Probe(
            name=(
                "Authentik OIDC discovery "
                f"(expected tunnel {PRODUCTION_TUNNEL_NAME})"
            ),
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
        login_probe(web, auth_base_url),
        Probe(
            name="unauthenticated session",
            url=f"{web}/api/auth/session",
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
        ),
        Probe(
            name="Coach page route",
            url=f"{web}/coach",
            expected_statuses=(200,),
            route_contract=True,
        ),
        Probe(
            name="Progress page route",
            url=f"{web}/progress",
            expected_statuses=(200,),
            route_contract=True,
        ),
        Probe(
            name="Training page route",
            url=f"{web}/training",
            expected_statuses=(200,),
            route_contract=True,
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
        ),
        Probe(
            name="authenticated Today decision context",
            url=f"{web}/api/today-plan/context",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
            required_json_keys=("week", "trajectory", "match"),
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
            name="authenticated athlete journey",
            url=f"{web}/api/journey?window=30d&sport=all&goal=all",
            expected_statuses=(200,),
            headers={"Authorization": f"Bearer {auth_token}"},
            require_json_object=True,
        ),
    ]


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
) -> None:
    """Verify every mandatory production probe."""
    if not auth_token:
        raise SystemExit("RUNTRAINER_SMOKE_AUTH_TOKEN is required")
    if route_timeout_seconds is None:
        route_timeout_seconds = timeout_seconds
    for probe in production_probes(
        expected_release=expected_release,
        auth_token=auth_token,
        **urls,
    ):
        verify_probe(
            probe,
            timeout_seconds=(
                route_timeout_seconds if probe.route_contract else timeout_seconds
            ),
            retry_interval_seconds=retry_interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
            opener=opener,
        )


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
