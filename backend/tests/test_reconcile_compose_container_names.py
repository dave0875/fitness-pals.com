"""Safety contracts for one-time Compose container-name reconciliation."""

from __future__ import annotations

import io
from pathlib import Path
import tarfile
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import reconcile_compose_container_names as reconciliation
from scripts.reconcile_compose_container_names import (
    ContainerConflictError,
    ReconciliationPlan,
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
    running: bool = True,
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
        "State": {"Running": running},
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


@pytest.mark.parametrize("service", ["influxdb", "grafana"])
def test_production_deploy_project_is_a_recognized_legacy_owner(service: str):
    assert (
        classify_container(
            _container(service, project="fitness-pals-deploy"),
            SERVICE_SPECS[service],
            current_project="fitness-palscom",
            legacy_projects={"fitness-pals-deploy"},
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
    container_id = "legacy-grafana-container-id"
    commands: list[list[str]] = []
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation, "_inspect", lambda _container_id: _container("grafana")
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    reconciliation.reconcile_service(
        "grafana",
        current_project="fitness-palscom",
        legacy_projects={"garmin-grafana"},
    )

    assert commands == [
        ["docker", "stop", "--time", "60", container_id],
        ["docker", "rm", container_id],
    ]
    assert all("-v" not in command for command in commands)


def test_influxdb_replacement_requires_a_backup_destination_before_mutation(
    monkeypatch,
):
    container_id = "legacy-influxdb-container-id"
    commands: list[list[str]] = []
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation,
        "_inspect",
        lambda _container_id: _container(
            "influxdb", project="fitness-pals-deploy"
        ),
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    with pytest.raises(ContainerConflictError, match="backup directory is required"):
        reconciliation.reconcile_services(
            ["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"fitness-pals-deploy"},
        )

    assert commands == []


def test_stopped_influxdb_fails_before_backup_or_removal(monkeypatch, tmp_path):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        reconciliation, "_container_ids", lambda _name: ["stopped-influxdb"]
    )
    monkeypatch.setattr(
        reconciliation,
        "_inspect",
        lambda _container_id: _container(
            "influxdb", project="fitness-pals-deploy", running=False
        ),
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    with pytest.raises(ContainerConflictError, match="must be running"):
        reconciliation.reconcile_services(
            ["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"fitness-pals-deploy"},
            backup_dir=tmp_path,
        )

    assert commands == []


def test_portable_influxdb_backup_completes_before_stop_and_removal(
    monkeypatch, tmp_path
):
    container_id = "legacy-influxdb-container-id"
    events: list[str] = []
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation,
        "_inspect",
        lambda _container_id: _container(
            "influxdb", project="fitness-pals-deploy"
        ),
    )
    monkeypatch.setattr(
        reconciliation,
        "_preflight_backup_destination",
        lambda _plan, _backup_dir: events.append("preflight"),
    )
    monkeypatch.setattr(
        reconciliation,
        "_create_influxdb_backup",
        lambda _plan, _backup_dir: events.append("backup"),
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: events.append(" ".join(command))
        or SimpleNamespace(),
    )

    reconciliation.reconcile_services(
        ["influxdb"],
        current_project="fitness-palscom",
        legacy_projects={"fitness-pals-deploy"},
        backup_dir=tmp_path,
    )

    assert events == [
        "preflight",
        "backup",
        f"docker stop --time 60 {container_id}",
        f"docker rm {container_id}",
    ]


def test_portable_backup_uses_same_image_and_writes_verified_checksums(
    monkeypatch, tmp_path
):
    container_id = "legacy-influxdb-container-id"
    commands: list[list[str]] = []
    plan = ReconciliationPlan(
        service="influxdb",
        spec=SERVICE_SPECS["influxdb"],
        container_id=container_id,
        action="replace",
        was_running=True,
        image="influxdb:1.11",
    )

    def run(command: list[str], **_kwargs):
        commands.append(command)
        backup_name = command[-1].rsplit("/", maxsplit=1)[-1]
        backup_path = tmp_path / backup_name
        backup_path.mkdir()
        (backup_path / "20260908T120000Z.manifest").write_text(
            "manifest", encoding="utf-8"
        )
        (backup_path / "20260908T120000Z.meta").write_bytes(b"metadata")
        with tarfile.open(
            backup_path / "20260908T120000Z.s00.tar.gz", mode="w:gz"
        ) as archive:
            payload = b"shard data"
            member = tarfile.TarInfo("shard")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        return SimpleNamespace()

    monkeypatch.setattr(reconciliation.subprocess, "run", run)

    reconciliation._create_influxdb_backup(plan, tmp_path)

    assert len(commands) == 1
    command = commands[0]
    assert command[:3] == [
        "docker",
        "run",
        "--rm",
    ]
    assert command[command.index("--network") : command.index("--mount")] == [
        "--network",
        f"container:{container_id}",
    ]
    assert "--user" in command
    assert f"type=bind,src={tmp_path},dst=/backup" in command
    assert command[command.index("--entrypoint") + 1 : -3] == [
        "influxd",
        "influxdb:1.11",
    ]
    backup_path = next(path for path in tmp_path.iterdir() if path.is_dir())
    checksums = (backup_path / "SHA256SUMS").read_text(encoding="utf-8")
    assert "20260908T120000Z.manifest" in checksums
    assert "20260908T120000Z.meta" in checksums
    assert "20260908T120000Z.s00.tar.gz" in checksums


def test_backup_destination_preflight_verifies_host_and_docker_write_access(
    monkeypatch, tmp_path
):
    commands: list[list[str]] = []
    plan = ReconciliationPlan(
        service="influxdb",
        spec=SERVICE_SPECS["influxdb"],
        container_id="legacy-influxdb-container-id",
        action="replace",
        was_running=True,
        image="influxdb:1.11",
    )

    def run(command: list[str], **_kwargs):
        commands.append(command)
        docker_probe = tmp_path / command[-1]
        docker_probe.write_text("docker probe", encoding="utf-8")
        return SimpleNamespace()

    monkeypatch.setattr(reconciliation.subprocess, "run", run)

    reconciliation._preflight_backup_destination(plan, tmp_path)

    assert len(commands) == 1
    command = commands[0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--user") + 1] == (
        f"{reconciliation.os.getuid()}:{reconciliation.os.getgid()}"
    )
    assert f"type=bind,src={tmp_path},dst=/backup" in command
    assert command[command.index("--entrypoint") + 1 : -4] == [
        "sh",
        "influxdb:1.11",
    ]
    assert command[-4:-1] == [
        "-c",
        'set -eu; probe="/backup/$1"; : > "$probe"; rm -f "$probe"',
        "reconcile-preflight",
    ]
    assert command[-1].startswith(".docker-write-probe-")
    assert list(tmp_path.iterdir()) == []


def test_dry_run_preflights_backup_without_changing_containers(
    monkeypatch, tmp_path, capsys
):
    container_id = "legacy-influxdb-container-id"
    commands: list[list[str]] = []
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation,
        "_inspect",
        lambda _container_id: _container(
            "influxdb", project="fitness-pals-deploy"
        ),
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    reconciliation.reconcile_services(
        ["influxdb"],
        current_project="fitness-palscom",
        legacy_projects={"fitness-pals-deploy"},
        backup_dir=tmp_path,
        dry_run=True,
    )

    assert len(commands) == 1
    assert commands[0][:3] == ["docker", "run", "--rm"]
    assert "--network" not in commands[0]
    assert not any(command[:2] == ["docker", "stop"] for command in commands)
    assert not any(command[:2] == ["docker", "rm"] for command in commands)
    assert "Would remove verified legacy /influxdb" in capsys.readouterr().out


def test_inaccessible_backup_destination_fails_before_container_mutation(
    monkeypatch, tmp_path
):
    container_id = "legacy-influxdb-container-id"
    commands: list[list[str]] = []
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("blocks directory creation", encoding="utf-8")
    monkeypatch.setattr(reconciliation, "_container_ids", lambda _name: [container_id])
    monkeypatch.setattr(
        reconciliation,
        "_inspect",
        lambda _container_id: _container(
            "influxdb", project="fitness-pals-deploy"
        ),
    )
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    with pytest.raises(OSError):
        reconciliation.reconcile_services(
            ["influxdb"],
            current_project="fitness-palscom",
            legacy_projects={"fitness-pals-deploy"},
            backup_dir=parent_file / "backups",
        )

    assert commands == []


def test_every_service_is_validated_before_any_container_is_removed(monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        reconciliation,
        "_container_ids",
        lambda name: [f"legacy-{name}-container-id"],
    )

    def inspect(container_id: str):
        if "influxdb" in container_id:
            return _container("influxdb", project="fitness-pals-deploy")
        return _container(
            "grafana", project="fitness-pals-deploy", image="postgres:18"
        )

    monkeypatch.setattr(reconciliation, "_inspect", inspect)
    monkeypatch.setattr(
        reconciliation.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(),
    )

    with pytest.raises(ContainerConflictError, match="unexpected image"):
        reconciliation.reconcile_services(
            ["influxdb", "grafana"],
            current_project="fitness-palscom",
            legacy_projects={"fitness-pals-deploy"},
        )

    assert commands == []


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
    override: dict[str, Any], message: str
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
    assert (
        "STATEFUL_BACKUP_DIR: "
        "/home/ghrunner/fitness-pals-backups/pre-compose-migration"
    ) in prod_job
    assert "scripts/reconcile_compose_container_names.py" in guard_step
    assert '--project "$COMPOSE_PROJECT_NAME"' in guard_step
    assert '--backup-dir "$STATEFUL_BACKUP_DIR"' in guard_step
    assert "--legacy-project garmin-grafana" in guard_step
    assert "--legacy-project fitness-pals-deploy" in guard_step
    assert "influxdb" in guard_step
    assert "grafana" in guard_step


def test_branch_dispatch_preflights_production_container_and_backup_destination():
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )
    test_job = workflow.split("  test:\n", maxsplit=1)[1].split(
        "  deploy-dev:\n", maxsplit=1
    )[0]

    assert "preflight_prod_containers:" in workflow
    assert "Preflight production container and backup destination" in test_job
    assert "inputs.preflight_prod_containers" in test_job
    assert "--dry-run" in test_job
    assert (
        "--backup-dir "
        "/home/ghrunner/fitness-pals-backups/pre-compose-migration"
    ) in test_job
    assert "--legacy-project fitness-pals-deploy" in test_job
