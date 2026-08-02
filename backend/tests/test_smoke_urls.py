"""Tests for deploy smoke URL checks."""

from __future__ import annotations

import pytest

from scripts import smoke_urls


def test_wait_for_url_passes_cloudflare_simulation_with_default_user_agent():
    """A curl-like user agent should bypass the local Cloudflare 403 simulator."""
    smoke_urls.wait_for_url(
        "https://fitness-pals.com/auth/login",
        timeout_seconds=1,
        test_mode="cloudflare-403",
        retry_interval_seconds=0,
    )


def test_wait_for_url_uses_configured_request_timeout(monkeypatch):
    """Readiness probes should honor the per-request timeout budget."""
    seen_timeouts: list[int] = []

    def fake_urlopen(request, timeout):
        del request
        seen_timeouts.append(timeout)
        return smoke_urls._FakeResponse(200)

    monkeypatch.setattr(smoke_urls, "_urlopen_for_test_mode", lambda test_mode: fake_urlopen)

    smoke_urls.wait_for_url(
        "http://127.0.0.1:8000/ready",
        timeout_seconds=1,
        request_timeout_seconds=15,
        retry_interval_seconds=0,
    )

    assert seen_timeouts == [15]


def test_wait_for_url_fails_cloudflare_simulation_without_user_agent():
    """An empty user agent should keep failing the Cloudflare 403 simulator."""
    with pytest.raises(SystemExit, match="Timed out waiting for https://fitness-pals.com/auth/login"):
        smoke_urls.wait_for_url(
            "https://fitness-pals.com/auth/login",
            timeout_seconds=0,
            user_agent="",
            test_mode="cloudflare-403",
            retry_interval_seconds=0,
        )


def test_main_supports_cloudflare_test_mode_and_request_timeout(monkeypatch):
    """The CLI should expose local smoke controls used by CI and local verification."""
    seen: list[tuple[str, int, int, str | None]] = []

    def fake_wait_for_url(
        url: str,
        timeout_seconds: int,
        *,
        user_agent: str = smoke_urls.DEFAULT_USER_AGENT,
        test_mode: str | None = None,
        retry_interval_seconds: float = 2,
        request_timeout_seconds: int = 5,
    ) -> None:
        del user_agent, retry_interval_seconds
        seen.append((url, timeout_seconds, request_timeout_seconds, test_mode))

    monkeypatch.setattr(smoke_urls, "wait_for_url", fake_wait_for_url)
    monkeypatch.setattr(
        "sys.argv",
        [
            "smoke_urls.py",
            "--urls",
            "https://fitness-pals.com/auth/login",
            "--timeout",
            "1",
            "--request-timeout",
            "15",
            "--test-mode",
            "cloudflare-403",
        ],
    )

    assert smoke_urls.main() == 0
    assert seen == [("https://fitness-pals.com/auth/login", 1, 15, "cloudflare-403")]


def test_wait_for_url_requires_expected_release_text(monkeypatch):
    """A healthy response with stale release content must not pass deployment."""
    responses = iter(
        [
            smoke_urls._FakeResponse(200, b"old-release"),
            smoke_urls._FakeResponse(200, b"expected-release"),
        ]
    )

    def fake_urlopen(request, timeout):
        del request, timeout
        return next(responses)

    monkeypatch.setattr(smoke_urls, "_urlopen_for_test_mode", lambda test_mode: fake_urlopen)

    smoke_urls.wait_for_url(
        "https://fitness-pals.com/deploy-version",
        timeout_seconds=1,
        expected_text="expected-release",
        retry_interval_seconds=0,
    )
