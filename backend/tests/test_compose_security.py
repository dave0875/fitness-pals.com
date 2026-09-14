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
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_ID=${GRAFANA_OIDC_CLIENT_ID:-}" in grafana
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET=${GRAFANA_OIDC_CLIENT_SECRET:-}" in grafana
    assert "contains(groups[*], 'Grafana Admins') && 'Admin' || 'Viewer'" in grafana
    assert "GF_AUTH_OAUTH_AUTO_LOGIN=true" in grafana
    bootstrap = _service_block(compose_text, "authentik-bootstrap")
    assert "--grafana-sso" in bootstrap
    assert "GRAFANA_OIDC_CLIENT_ID=${GRAFANA_OIDC_CLIENT_ID:-}" in bootstrap
    assert "GRAFANA_OIDC_CLIENT_SECRET=${GRAFANA_OIDC_CLIENT_SECRET:-}" in bootstrap


def test_compose_defers_pythonpath_expansion_to_the_backend_container():
    """Host PYTHONPATH is unrelated to the backend container command."""
    compose_text = (REPOSITORY_ROOT / "compose.yml").read_text(encoding="utf-8")
    backend = _service_block(compose_text, "backend")

    assert 'export PYTHONPATH="$${PYTHONPATH}:/app"' in backend
    assert "export PYTHONPATH=$PYTHONPATH:/app" not in backend


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


def test_deploy_jobs_receive_and_preflight_environment_scoped_grafana_secrets():
    """Runner env files cannot silently drift from required Grafana credentials."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]
    prod_job = workflow_text.split("  deploy-prod:\n", maxsplit=1)[1]

    assert "GRAFANA_OIDC_CLIENT_ID: ${{ secrets.DEV_GRAFANA_OIDC_CLIENT_ID }}" in dev_job
    assert (
        "GRAFANA_OIDC_CLIENT_SECRET: ${{ secrets.DEV_GRAFANA_OIDC_CLIENT_SECRET }}"
        in dev_job
    )
    assert "GRAFANA_OIDC_CLIENT_ID: ${{ secrets.GRAFANA_OIDC_CLIENT_ID }}" in prod_job
    assert (
        "GRAFANA_OIDC_CLIENT_SECRET: ${{ secrets.GRAFANA_OIDC_CLIENT_SECRET }}"
        in prod_job
    )
    for job in (dev_job, prod_job):
        assert "Validate Grafana OIDC deployment secrets" in job
        assert 'if [ -z "$GRAFANA_OIDC_CLIENT_ID" ]' in job
        assert 'if [ -z "$GRAFANA_OIDC_CLIENT_SECRET" ]' in job
        assert job.index("Validate Grafana OIDC deployment secrets") < job.index(
            "Assemble env from base and overlay"
        )
        assert job.index("Validate Grafana OIDC deployment secrets") < job.index(
            "Validate compose config"
        )


def test_dev_reconciles_infrastructure_before_app_only_restart():
    """Dependency changes must use the full reconcile path before app restarts."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]
    restart_step = dev_job.split(
        "      - name: Restart changed app services\n", maxsplit=1
    )[1].split("\n      - name:", maxsplit=1)[0]

    assert dev_job.index("Reconcile complete dev runtime") < dev_job.index(
        "Restart changed app services"
    )
    for service in ("postgres", "influxdb", "grafana", "cloudflared"):
        assert f"steps.changes.outputs.{service}_changed != 'true'" in restart_step


def test_dev_failure_diagnostics_are_non_secret_and_non_masking():
    """A failed deployment reports service state without dumping environments."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]
    diagnostics = dev_job.split(
        "      - name: Capture dev deployment failure diagnostics\n", maxsplit=1
    )[1].split("\n      - name:", maxsplit=1)[0]

    assert "if: failure()" in diagnostics
    assert "continue-on-error: true" in diagnostics
    assert 'docker compose --env-file "$ENV_FILE" ps --all' in diagnostics
    assert "logs --no-color --tail=200" in diagnostics
    assert "runtrainer-postgres" in diagnostics
    assert "authentik-server" in diagnostics
    assert "authentik-worker" in diagnostics
    assert "docker inspect --format" in diagnostics
    assert ".Config.Env" not in diagnostics


def test_explicit_branch_dispatch_deploys_complete_dev_runtime_only():
    """A branch can prove deployment on dev without ever targeting production."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    dev_job = workflow_text.split("  deploy-dev:\n", maxsplit=1)[1].split(
        "  deploy-prod:\n", maxsplit=1
    )[0]
    prod_job = workflow_text.split("  deploy-prod:\n", maxsplit=1)[1]

    assert "deploy_dev:" in workflow_text
    assert "github.event_name == 'workflow_dispatch' && inputs.deploy_dev" in dev_job
    assert "Reconcile complete dev runtime" in dev_job
    for service in (
        "runtrainer-postgres",
        "influxdb",
        "grafana",
        "authentik-redis",
        "authentik-server",
        "authentik-worker",
        "backend",
        "worker",
        "training-agent",
        "frontend",
        "cloudflared",
        "cloudflared-loopback",
    ):
        assert service in dev_job
    assert "if: github.ref == 'refs/heads/main'" in prod_job
    assert "inputs.deploy_dev" not in prod_job


def test_ci_renders_both_compose_deployment_variants():
    """PR CI proves Compose inspection needs no Grafana credentials or PYTHONPATH."""
    workflow_text = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    test_job = workflow_text.split("  test:\n", maxsplit=1)[1].split(
        "  deploy-dev:\n", maxsplit=1
    )[0]

    assert "GRAFANA_OIDC_CLIENT_ID: ci-grafana-client" not in test_job
    assert "GRAFANA_OIDC_CLIENT_SECRET: ci-grafana-secret" not in test_job
    assert "Validate deployment Compose configurations" in test_job
    assert "env -u PYTHONPATH" in test_job
    assert "GRAFANA_OIDC_CLIENT_ID=" in test_job
    assert "GRAFANA_OIDC_CLIENT_SECRET=" in test_job
    assert "docker compose --env-file .env.production config -q" in test_job
    assert "COMPOSE_FILE=compose.yml:compose.dev.yml" in test_job
