#!/usr/bin/env python3
"""Smoke-check one or more HTTP URLs until they return a healthy response."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from http.client import HTTPMessage
from types import TracebackType
from typing import Literal

DEFAULT_USER_AGENT = "curl/8.7.1 fitness-pals-smoke/1.0"
TEST_MODE_CLOUDFLARE_403 = "cloudflare-403"


def parse_urls(raw_urls: str) -> list[str]:
    """Split comma/newline-delimited URLs into a cleaned list."""
    urls: list[str] = []
    for chunk in raw_urls.replace("\n", ",").split(","):
        candidate = chunk.strip()
        if candidate:
            urls.append(candidate)
    return urls


class _FakeResponse:
    """Small context-manager response used by local smoke test modes."""

    def __init__(self, status: int):
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, exc_tb
        return False


def _looks_like_browser_or_curl(user_agent: str) -> bool:
    """Return True when the user-agent should pass Cloudflare-style checks."""
    normalized = user_agent.lower()
    return "curl/" in normalized or "mozilla/" in normalized


def _cloudflare_test_urlopen(request: urllib.request.Request, timeout: int = 5) -> _FakeResponse:
    """Simulate Cloudflare blocking requests that lack a browser-like user-agent."""
    del timeout
    user_agent = request.headers.get("User-Agent") or request.headers.get("User-agent") or ""
    if _looks_like_browser_or_curl(user_agent):
        return _FakeResponse(200)
    raise urllib.error.HTTPError(
        request.full_url,
        403,
        "Forbidden",
        hdrs=HTTPMessage(),
        fp=None,
    )


def _urlopen_for_test_mode(test_mode: str | None):
    """Return the appropriate urlopen implementation for a given local test mode."""
    if test_mode == TEST_MODE_CLOUDFLARE_403:
        return _cloudflare_test_urlopen
    return urllib.request.urlopen


def _build_request(url: str, user_agent: str) -> urllib.request.Request:
    """Construct a request with the smoke checker user-agent when provided."""
    headers = {"User-Agent": user_agent} if user_agent else {}
    return urllib.request.Request(url, headers=headers)


def wait_for_url(
    url: str,
    timeout_seconds: int,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    test_mode: str | None = None,
    retry_interval_seconds: float = 2,
    request_timeout_seconds: int = 5,
) -> None:
    """Wait until a URL returns a healthy HTTP response or raise SystemExit."""
    deadline = time.time() + timeout_seconds
    opener = _urlopen_for_test_mode(test_mode)
    last_error: Exception | str | None = None
    while True:
        try:
            with opener(
                _build_request(url, user_agent), timeout=request_timeout_seconds
            ) as response:
                if 200 <= response.status < 400:
                    return
                last_error = f"Unexpected HTTP status {response.status}"
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
        if time.time() >= deadline:
            break
        time.sleep(retry_interval_seconds)
    if last_error:
        raise SystemExit(f"Timed out waiting for {url}; last error: {last_error}")
    raise SystemExit(f"Timed out waiting for {url}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", required=True, help="Comma or newline-delimited list of URLs")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--request-timeout", type=int, default=5)
    parser.add_argument(
        "--test-mode",
        choices=[TEST_MODE_CLOUDFLARE_403],
        help="Local-only simulation mode for smoke checker verification.",
    )
    args = parser.parse_args()

    urls = parse_urls(args.urls)
    if not urls:
        raise SystemExit("No smoke-check URLs were provided")

    for url in urls:
        wait_for_url(
            url,
            args.timeout,
            test_mode=args.test_mode,
            request_timeout_seconds=args.request_timeout,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
