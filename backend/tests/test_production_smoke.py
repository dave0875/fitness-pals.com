"""Tests for semantic public production smoke checks."""

from __future__ import annotations

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


def test_production_smoke_proves_public_and_authenticated_contracts() -> None:
    token = "short-lived-token"
    release = "abc123"
    seen: list[tuple[str, str | None]] = []

    def opener(request, timeout):
        del timeout
        url = request.full_url
        authorization = request.headers.get("Authorization")
        seen.append((url, authorization))
        if url.endswith("/auth/login?next=%2Fjourney"):
            return FakeResponse(
                302,
                headers={
                    "Location": "https://auth.fitness-pals.com/application/o/authorize/"
                },
            )
        if any(url.endswith(route) for route in ("/today", "/coach", "/progress", "/training")):
            return FakeResponse(200, "<html>Fitness Pals</html>")
        if url.endswith("/api/auth/session"):
            raise http_error(url, 401, {"detail": "Credentials missing"})
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
        if "/api/journey?" in url:
            assert authorization == f"Bearer {token}"
            return FakeResponse(200, {"state": "empty", "activities": []})
        raise AssertionError(f"unexpected URL {url}")

    smoke_production.verify_production(
        expected_release=release,
        auth_token=token,
        timeout_seconds=1,
        route_timeout_seconds=1,
        retry_interval_seconds=0,
        opener=opener,
    )

    assert len(seen) == 14
    assert sum(authorization is not None for _, authorization in seen) == 1


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
