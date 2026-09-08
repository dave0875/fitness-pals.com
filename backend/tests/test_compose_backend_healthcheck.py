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


def test_backend_host_port_is_configurable_with_legacy_default():
    """Shared hosts can override port 8000 without changing the container port."""
    repository_root = Path(__file__).resolve().parents[2]
    compose_text = (repository_root / "compose.dev.yml").read_text(
        encoding="utf-8"
    )
    workflow_text = (repository_root / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]

    assert '127.0.0.1:${RUNTRAINER_BACKEND_HOST_PORT:-8000}:8000' in compose_text
    assert "COMPOSE_FILE: compose.yml:compose.dev.yml" in dev_job


def test_dev_backend_smoke_uses_configured_host_port():
    """The dev readiness probe must follow the same host-port override as Compose."""
    repository_root = Path(__file__).resolve().parents[2]
    workflow_text = (repository_root / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]

    assert "BACKEND_HOST_PORT=" in dev_job
    assert "RUNTRAINER_BACKEND_HOST_PORT --default 8000" in dev_job
    assert 'http://127.0.0.1:${BACKEND_HOST_PORT}/ready' in dev_job
    assert 'urls+=("http://127.0.0.1:8000/ready")' not in dev_job
