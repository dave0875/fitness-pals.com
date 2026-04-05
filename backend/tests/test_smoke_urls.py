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


def test_main_supports_cloudflare_test_mode(monkeypatch):
    """The CLI should expose a local test mode for Cloudflare-style 403 simulation."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "smoke_urls.py",
            "--urls",
            "https://fitness-pals.com/auth/login",
            "--timeout",
            "1",
            "--test-mode",
            "cloudflare-403",
        ],
    )

    assert smoke_urls.main() == 0
