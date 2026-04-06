"""Regression tests for backend healthcheck wiring in compose."""

from __future__ import annotations

from pathlib import Path


def test_backend_compose_healthcheck_matches_warmup_budget():
    """Dev backend healthchecks should use Python and realistic startup thresholds."""
    compose_text = (Path(__file__).resolve().parents[2] / "compose.yml").read_text(
        encoding="utf-8"
    )
    backend_block = compose_text.split("\n  backend:\n", maxsplit=1)[1].split(
        "\n  worker:\n", maxsplit=1
    )[0]

    assert (
        "python3 -c "
        '"import sys, urllib.request; resp = urllib.request.urlopen'
        "('http://localhost:8000/ready'); "
        'sys.exit(0) if resp.getcode() == 200 else sys.exit(1)"'
    ) in backend_block
    assert "      interval: 10s" in backend_block
    assert "      timeout: 15s" in backend_block
    assert "      retries: 10" in backend_block
    assert "      start_period: 30s" in backend_block
