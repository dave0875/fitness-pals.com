#!/usr/bin/env python3
"""Safely replace legacy stateful containers that block Compose fixed names."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Literal, Mapping, Sequence
import uuid


class ContainerConflictError(RuntimeError):
    """The exact-name container cannot be proven safe to replace."""


@dataclass(frozen=True)
class ServiceSpec:
    container_name: str
    image_repositories: tuple[str, ...]
    volume_name: str
    volume_destination: str


@dataclass(frozen=True)
class ReconciliationPlan:
    service: str
    spec: ServiceSpec
    container_id: str | None
    action: Literal["absent", "keep", "replace"]
    was_running: bool = False
    image: str | None = None


SERVICE_SPECS = {
    "influxdb": ServiceSpec(
        container_name="influxdb",
        image_repositories=("influxdb", "docker.io/library/influxdb"),
        volume_name="garmin-grafana_influxdb_data",
        volume_destination="/var/lib/influxdb",
    ),
    "grafana": ServiceSpec(
        container_name="grafana",
        image_repositories=("grafana/grafana", "docker.io/grafana/grafana"),
        volume_name="garmin-grafana_grafana_data",
        volume_destination="/var/lib/grafana",
    ),
}


def _image_repository(image: str) -> str:
    without_digest = image.split("@", maxsplit=1)[0]
    final_slash = without_digest.rfind("/")
    final_colon = without_digest.rfind(":")
    if final_colon > final_slash:
        return without_digest[:final_colon]
    return without_digest


def classify_container(
    container: Mapping[str, object],
    spec: ServiceSpec,
    *,
    current_project: str,
    legacy_projects: set[str],
) -> Literal["keep", "replace"]:
    """Classify an exact-name container, rejecting anything not provably expected."""
    name = str(container.get("Name", ""))
    if name != f"/{spec.container_name}":
        raise ContainerConflictError(
            f"container has unexpected name {name!r}; expected '/{spec.container_name}'"
        )

    config = container.get("Config")
    if not isinstance(config, Mapping):
        raise ContainerConflictError("container inspection has no Config metadata")
    raw_labels = config.get("Labels") or {}
    if not isinstance(raw_labels, Mapping):
        raise ContainerConflictError("container inspection has invalid labels")
    labels = {str(key): str(value) for key, value in raw_labels.items()}

    project = labels.get("com.docker.compose.project")
    service = labels.get("com.docker.compose.service")
    if project == current_project:
        if service != spec.container_name:
            raise ContainerConflictError(
                f"current-project container has unexpected Compose service {service!r}"
            )
        return "keep"

    if project is not None and project not in legacy_projects:
        raise ContainerConflictError(f"container belongs to unexpected Compose project {project!r}")
    if service is not None and service != spec.container_name:
        raise ContainerConflictError(f"container has unexpected Compose service {service!r}")

    image = str(config.get("Image", ""))
    if _image_repository(image) not in spec.image_repositories:
        raise ContainerConflictError(f"container uses unexpected image {image!r}")

    raw_mounts = container.get("Mounts") or []
    if not isinstance(raw_mounts, Sequence):
        raise ContainerConflictError("container inspection has invalid mounts")
    has_required_volume = any(
        isinstance(mount, Mapping)
        and mount.get("Type") == "volume"
        and mount.get("Name") == spec.volume_name
        and mount.get("Destination") == spec.volume_destination
        for mount in raw_mounts
    )
    if not has_required_volume:
        raise ContainerConflictError(
            "container is not attached to the required named volume "
            f"{spec.volume_name!r} at {spec.volume_destination!r}"
        )

    return "replace"


def _container_ids(name: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _inspect(container_id: str) -> Mapping[str, object]:
    result = subprocess.run(
        ["docker", "inspect", container_id],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = json.loads(result.stdout)
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise ContainerConflictError(
            f"docker inspect returned an unexpected result for {container_id}"
        )
    container = inspected[0]
    if not isinstance(container, Mapping):
        raise ContainerConflictError(
            f"docker inspect returned invalid metadata for {container_id}"
        )
    return container


def _plan_service(
    service: str, *, current_project: str, legacy_projects: set[str]
) -> ReconciliationPlan:
    spec = SERVICE_SPECS[service]
    container_ids = _container_ids(spec.container_name)
    if not container_ids:
        return ReconciliationPlan(service, spec, None, "absent")
    if len(container_ids) != 1:
        raise ContainerConflictError(
            f"expected at most one /{spec.container_name} container, found {len(container_ids)}"
        )

    container_id = container_ids[0]
    inspected = _inspect(container_id)
    action = classify_container(
        inspected,
        spec,
        current_project=current_project,
        legacy_projects=legacy_projects,
    )
    state = inspected.get("State") or {}
    was_running = isinstance(state, Mapping) and state.get("Running") is True
    config = inspected.get("Config") or {}
    image = str(config.get("Image", "")) if isinstance(config, Mapping) else ""
    return ReconciliationPlan(
        service=service,
        spec=spec,
        container_id=container_id,
        action=action,
        was_running=was_running,
        image=image,
    )


def _validate_portable_backup(backup_path: Path) -> list[Path]:
    if not backup_path.is_dir():
        raise ContainerConflictError(
            f"InfluxDB portable backup was not copied to {backup_path}"
        )
    files = sorted(path for path in backup_path.iterdir() if path.is_file())
    manifests = [path for path in files if path.suffix == ".manifest"]
    metadata = [path for path in files if path.suffix == ".meta"]
    shards = [path for path in files if path.name.endswith(".tar.gz")]
    if not manifests or not metadata or not shards:
        raise ContainerConflictError(
            "InfluxDB portable backup is incomplete; expected manifest, metadata, "
            "and shard archive files"
        )
    for path in files:
        if path.stat().st_size == 0:
            raise ContainerConflictError(f"InfluxDB backup file is empty: {path.name}")
    for shard in shards:
        try:
            with tarfile.open(shard, mode="r:gz") as archive:
                archive.getmembers()
        except (tarfile.TarError, OSError) as exc:
            raise ContainerConflictError(
                f"InfluxDB shard backup is unreadable: {shard.name}: {exc}"
            ) from exc
    return files


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preflight_backup_destination(
    plan: ReconciliationPlan, backup_dir: Path
) -> None:
    """Prove the runner and backup sidecar can write the durable host path."""
    if not plan.image:
        raise ContainerConflictError(
            "cannot preflight the backup destination without the InfluxDB image identity"
        )

    backup_root = backup_dir.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    host_probe: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=backup_root,
            prefix=".host-write-probe-",
            delete=False,
        ) as probe:
            host_probe = Path(probe.name)
            probe.write(b"backup destination preflight\n")
            probe.flush()
            os.fsync(probe.fileno())
    finally:
        if host_probe is not None:
            host_probe.unlink(missing_ok=True)

    docker_probe_name = f".docker-write-probe-{uuid.uuid4().hex}"
    docker_probe = backup_root / docker_probe_name
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={backup_root},dst=/backup",
                "--entrypoint",
                "sh",
                plan.image,
                "-c",
                'set -eu; probe="/backup/$1"; : > "$probe"; rm -f "$probe"',
                "reconcile-preflight",
                docker_probe_name,
            ],
            check=True,
        )
    finally:
        docker_probe.unlink(missing_ok=True)

    print(f"Verified backup destination write access at {backup_root}.")


def _create_influxdb_backup(plan: ReconciliationPlan, backup_dir: Path) -> None:
    if plan.container_id is None:
        raise ContainerConflictError("cannot back up an absent InfluxDB container")
    if not plan.image:
        raise ContainerConflictError("cannot back up InfluxDB without its image identity")
    backup_root = backup_dir.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"influxdb-pre-compose-{stamp}-{plan.container_id[:12]}"
    host_path = backup_root / backup_name
    if host_path.exists():
        raise ContainerConflictError(f"backup destination already exists: {host_path}")

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--network",
            f"container:{plan.container_id}",
            "--mount",
            f"type=bind,src={backup_root},dst=/backup",
            "--entrypoint",
            "influxd",
            plan.image,
            "backup",
            "-portable",
            f"/backup/{backup_name}",
        ],
        check=True,
    )
    files = _validate_portable_backup(host_path)

    checksum_path = host_path / "SHA256SUMS"
    with checksum_path.open("w", encoding="utf-8") as checksum_file:
        for path in files:
            digest = _file_sha256(path)
            checksum_file.write(f"{digest}  {path.name}\n")
        checksum_file.flush()
        os.fsync(checksum_file.fileno())

    print(f"Verified portable InfluxDB backup at {host_path}.")


def _report_plan(plan: ReconciliationPlan, *, dry_run: bool) -> None:
    if plan.action == "absent":
        print(f"No existing /{plan.spec.container_name} container; nothing to migrate.")
        return
    if plan.container_id is None:
        raise ContainerConflictError("reconciliation plan is missing a container id")
    if plan.action == "keep":
        print(
            f"Keeping current-project /{plan.spec.container_name} container "
            f"{plan.container_id[:12]} "
            "for Docker Compose reconciliation."
        )
        return

    prefix = "Would remove" if dry_run else "Removing"
    print(
        f"{prefix} verified legacy /{plan.spec.container_name} container "
        f"{plan.container_id[:12]}; named volume {plan.spec.volume_name} is preserved."
    )


def reconcile_services(
    services: Sequence[str],
    *,
    current_project: str,
    legacy_projects: set[str],
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> None:
    """Validate every target, back up InfluxDB, then replace legacy containers."""
    plans = [
        _plan_service(
            service,
            current_project=current_project,
            legacy_projects=legacy_projects,
        )
        for service in services
    ]
    replacements = [plan for plan in plans if plan.action == "replace"]
    influx_replacements = [
        plan for plan in replacements if plan.service == "influxdb"
    ]

    if any(not plan.was_running for plan in influx_replacements):
        raise ContainerConflictError(
            "legacy InfluxDB must be running to create a portable backup"
        )
    if influx_replacements and backup_dir is None:
        raise ContainerConflictError(
            "an InfluxDB backup directory is required before container reconciliation"
        )

    for plan in influx_replacements:
        assert backup_dir is not None
        _preflight_backup_destination(plan, backup_dir)

    if dry_run:
        for plan in plans:
            _report_plan(plan, dry_run=True)
        return

    for plan in influx_replacements:
        assert backup_dir is not None
        _create_influxdb_backup(plan, backup_dir)

    stopped: list[ReconciliationPlan] = []
    removed_ids: set[str] = set()
    try:
        for plan in replacements:
            if plan.container_id is not None and plan.was_running:
                subprocess.run(
                    ["docker", "stop", "--time", "60", plan.container_id], check=True
                )
                stopped.append(plan)
        for plan in replacements:
            if plan.container_id is None:
                continue
            _report_plan(plan, dry_run=False)
            subprocess.run(["docker", "rm", plan.container_id], check=True)
            removed_ids.add(plan.container_id)
    except subprocess.CalledProcessError:
        for plan in reversed(stopped):
            if plan.container_id is not None and plan.container_id not in removed_ids:
                subprocess.run(["docker", "start", plan.container_id], check=False)
        raise

    for plan in plans:
        if plan.action != "replace":
            _report_plan(plan, dry_run=False)


def reconcile_service(
    service: str,
    *,
    current_project: str,
    legacy_projects: set[str],
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> None:
    reconcile_services(
        [service],
        current_project=current_project,
        legacy_projects=legacy_projects,
        backup_dir=backup_dir,
        dry_run=dry_run,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Current Compose project name")
    parser.add_argument(
        "--legacy-project",
        action="append",
        default=[],
        help="Recognized legacy Compose project (repeatable)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Host directory for the required portable InfluxDB backup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate container identity and backup destination, then report actions "
            "without backup, stop, or removal"
        ),
    )
    parser.add_argument("services", nargs="+", choices=sorted(SERVICE_SPECS))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        reconcile_services(
            args.services,
            current_project=args.project,
            legacy_projects=set(args.legacy_project),
            backup_dir=args.backup_dir,
            dry_run=args.dry_run,
        )
    except (
        ContainerConflictError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        print(f"Refusing unsafe container-name reconciliation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
