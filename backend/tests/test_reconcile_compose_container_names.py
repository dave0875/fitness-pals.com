"""Safety contracts for one-time Compose container-name reconciliation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import reconcile_compose_container_names as reconciliation
from scripts.reconcile_compose_container_names import (
    ContainerConflictError,
    SERVICE_SPECS,
    classify_container,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _container(
    service: str,
    *,
    project: str | None = "garmin-grafana",
    service_label: str | None = None,
    image: str | None = None,
    volume: str | None = None,
    destination: str | None = None,
) -> dict[str, object]:
    spec = SERVICE_SPECS[service]
    labels: dict[str, str] = {}
    if project is not None:
        labels["com.docker.compose.project"] = project
    if service_label is not None:
        labels["com.docker.compose.service"] = service_label
    elif project is not None:
        labels["com.docker.compose.service"] = service

    return {
        "Id": f"legacy-{service}",
        "Name": f"/{spec.container_name}",
        "Config": {"Image": image or spec.image_repositories[0], "Labels": labels},
        "Mounts": [
            {
                "Type": "volume",
                "Name": volume or spec.volume_name,
                "Destination": destination or spec.volume_destination,
            }
        ],
    }


@pytest.mark.parametrize("service", ["influxdb", "grafana"])
def test_recognized_legacy_compose_container_is_replaced(service: str):
    assert (
        classify_container(
            _container(service),
            SERVICE_SPECS[service],
            current_project="fitness-palscom",
            legacy_projects={"garmin-grafana"},
        )
        == "replace"
    )


def test_recognized_unlabelled_influxdb_is_replaced():
    assert (
        classify_container(
            _container("influxdb", project=None),
            SERVICE_SPECS["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"garmin-grafana"},
        )
        == "replace"
    )


def test_current_compose_container_is_left_for_compose():
    assert (
        classify_container(
            _container("influxdb", project="fitness-palscom"),
            SERVICE_SPECS["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"garmin-grafana"},
        )
        == "keep"
    )


def test_replacement_removes_only_the_container_and_never_its_volume(monkeypatch):
    container_id = "legacy-influxdb-container-id"
    commands: list[list[str]] = []
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation, "_inspect", lambda _container_id: _container("influxdb")
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    reconciliation.reconcile_service(
        "influxdb",
        current_project="fitness-palscom",
        legacy_projects={"garmin-grafana"},
    )

    assert commands == [["docker", "rm", "-f", container_id]]
    assert "-v" not in commands[0]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"project": "some-other-stack"}, "unexpected Compose project"),
        ({"service_label": "database"}, "unexpected Compose service"),
        ({"image": "postgres:18"}, "unexpected image"),
        ({"volume": "unrelated_data"}, "required named volume"),
        ({"destination": "/tmp/data"}, "required named volume"),
    ],
)
def test_unrecognized_container_fails_closed(
    override: dict[str, str], message: str
):
    with pytest.raises(ContainerConflictError, match=message):
        classify_container(
            _container("influxdb", **override),
            SERVICE_SPECS["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"garmin-grafana"},
        )


def test_production_workflow_runs_guard_before_compose_reconciliation():
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    prod_job = workflow.split("  deploy-prod:\n", maxsplit=1)[1]
    guard_position = prod_job.index("Reconcile legacy stateful container names")
    compose_position = prod_job.index("Reconcile complete production runtime")

    assert guard_position < compose_position
    guard_step = prod_job[guard_position:compose_position]
    assert "scripts/reconcile_compose_container_names.py" in guard_step
    assert '--project "$COMPOSE_PROJECT_NAME"' in guard_step
    assert "--legacy-project garmin-grafana" in guard_step
    assert "influxdb" in guard_step
    assert "grafana" in guard_step
