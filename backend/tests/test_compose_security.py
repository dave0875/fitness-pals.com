"""Security contracts for production and development Compose topology."""

from __future__ import annotations

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose_text: str, service: str) -> str:
    """Return one top-level Compose service block."""
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", compose_text
    )
    assert match is not None, f"Missing Compose service: {service}"
    return match.group(1)


def test_production_services_are_not_published_on_host():
    """Cloudflare ingress, not Docker host publishing, is the production edge."""
    compose_text = (REPOSITORY_ROOT / "compose.yml").read_text(encoding="utf-8")

    for service in (
        "influxdb",
        "grafana",
        "authentik-server",
        "backend",
        "training-agent",
    ):
        assert not re.search(r"(?m)^    ports:", _service_block(compose_text, service))


def test_development_ports_are_loopback_only():
    """Developer overrides must never publish debug services on every interface."""
    compose_text = (REPOSITORY_ROOT / "compose.dev.yml").read_text(encoding="utf-8")

    expected_bindings = {
        "influxdb": "127.0.0.1:${INFLUXDB_HOST_PORT:-8086}:8086",
        "grafana": "127.0.0.1:${GRAFANA_HOST_PORT:-3000}:3000",
        "authentik-server": "127.0.0.1:${AUTHENTIK_HOST_PORT:-9100}:9000",
        "backend": "127.0.0.1:${RUNTRAINER_BACKEND_HOST_PORT:-8000}:8000",
        "training-agent": "127.0.0.1:${TRAINING_AGENT_HOST_PORT:-9000}:9000",
    }
    for service, binding in expected_bindings.items():
        block = _service_block(compose_text, service)
        assert re.search(r"(?m)^    ports:", block)
        assert binding in block


def test_grafana_requires_authentik_and_least_privilege_roles():
    """Anonymous users can never receive Grafana access, especially Admin access."""
    compose_text = (REPOSITORY_ROOT / "compose.yml").read_text(encoding="utf-8")
    grafana = _service_block(compose_text, "grafana")

    assert "GF_AUTH_ANONYMOUS_ENABLED=false" in grafana
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer" in grafana
    assert "GF_AUTH_DISABLE_LOGIN_FORM=true" in grafana
    assert "GF_AUTH_BASIC_ENABLED=false" in grafana
    assert "GF_AUTH_GENERIC_OAUTH_ENABLED=true" in grafana
    assert "GF_AUTH_GENERIC_OAUTH_NAME=Authentik" in grafana
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_ID=${GRAFANA_OIDC_CLIENT_ID" in grafana
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET=${GRAFANA_OIDC_CLIENT_SECRET" in grafana
    assert "contains(groups[*], 'Grafana Admins') && 'Admin' || 'Viewer'" in grafana
    assert "GF_AUTH_OAUTH_AUTO_LOGIN=true" in grafana
    bootstrap = _service_block(compose_text, "authentik-bootstrap")
    assert "--grafana-sso" in bootstrap


def test_development_grafana_break_glass_stays_on_loopback():
    """Basic recovery login is enabled only by the loopback-bound dev overlay."""
    compose_text = (REPOSITORY_ROOT / "compose.dev.yml").read_text(encoding="utf-8")
    grafana = _service_block(compose_text, "grafana")

    assert "GF_AUTH_BASIC_ENABLED=true" in grafana
    assert "GF_AUTH_DISABLE_LOGIN_FORM=false" in grafana
    assert "GF_AUTH_OAUTH_AUTO_LOGIN=false" in grafana
    assert "127.0.0.1:${GRAFANA_HOST_PORT:-3000}:3000" in grafana


def test_authentik_worker_has_no_host_control():
    """Compromise of the Authentik worker must not imply Docker host control."""
    compose_text = (REPOSITORY_ROOT / "compose.yml").read_text(encoding="utf-8")
    worker = _service_block(compose_text, "authentik-worker")

    assert "\n    user: root" not in worker
    assert "/var/run/docker.sock" not in worker


def test_production_smoke_checks_private_service_endpoints():
    """Deployment verification must keep working without production host ports."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    prod_job = workflow_text.split("  deploy-prod:\n", maxsplit=1)[1]
    smoke_step = prod_job.split(
        "      - name: Smoke check complete local production runtime\n", maxsplit=1
    )[1].split("\n      - name:", maxsplit=1)[0]

    assert "docker compose --env-file \"$ENV_FILE\" exec -T backend" in smoke_step
    assert "http://backend:8000/ready" in smoke_step
    assert "http://training-agent:9000/ready" in smoke_step
    assert "http://grafana:3000/api/health" in smoke_step
    assert "http://127.0.0.1:" not in smoke_step


def test_development_training_agent_smoke_uses_configured_loopback_port():
    """The dev readiness probe follows the loopback-only Compose override."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]

    assert "TRAINING_AGENT_HOST_PORT --default 9000" in dev_job
    assert 'http://127.0.0.1:${TRAINING_AGENT_HOST_PORT}/ready' in dev_job
