"""Regression tests for backend healthcheck wiring in compose."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_backend_compose_healthcheck_matches_warmup_budget():
    """Dev backend healthchecks should use Python and realistic startup thresholds."""
    compose_path = Path(__file__).resolve().parents[2] / "compose.yml"
    with compose_path.open(encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)

    healthcheck = compose["services"]["backend"]["healthcheck"]

    assert healthcheck["test"] == [
        "CMD-SHELL",
        (
            'python3 -c "import sys, urllib.request; '
            "resp = urllib.request.urlopen('http://localhost:8000/ready'); "
            'sys.exit(0) if resp.getcode() == 200 else sys.exit(1)"\n'
        ),
    ]
    assert healthcheck["interval"] == "10s"
    assert healthcheck["timeout"] == "15s"
    assert healthcheck["retries"] == 10
    assert healthcheck["start_period"] == "30s"
