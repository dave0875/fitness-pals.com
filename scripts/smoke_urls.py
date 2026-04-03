#!/usr/bin/env python3
"""Smoke-check one or more HTTP URLs until they return 200."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request


def parse_urls(raw_urls: str) -> list[str]:
    """Split comma/newline-delimited URLs into a cleaned list."""
    urls: list[str] = []
    for chunk in raw_urls.replace("\n", ",").split(","):
        candidate = chunk.strip()
        if candidate:
            urls.append(candidate)
    return urls


def wait_for_url(url: str, timeout_seconds: int) -> None:
    """Wait until a URL returns HTTP 200 or raise SystemExit."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:  # pylint: disable=broad-except
            time.sleep(2)
    raise SystemExit(f"Timed out waiting for {url}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", required=True, help="Comma or newline-delimited list of URLs")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    urls = parse_urls(args.urls)
    if not urls:
        raise SystemExit("No smoke-check URLs were provided")

    for url in urls:
        wait_for_url(url, args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
