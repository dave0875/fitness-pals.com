#!/usr/bin/env python3
"""Safely replace legacy stateful containers that block Compose fixed names."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import subprocess
import sys
from typing import Literal, Mapping, Sequence


class ContainerConflictError(RuntimeError):
    """The exact-name container cannot be proven safe to replace."""


@dataclass(frozen=True)
class ServiceSpec:
    container_name: str
    image_repositories: tuple[str, ...]
    volume_name: str
    volume_destination: str


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


def reconcile_service(
    service: str, *, current_project: str, legacy_projects: set[str]
) -> None:
    spec = SERVICE_SPECS[service]
    container_ids = _container_ids(spec.container_name)
    if not container_ids:
        print(f"No existing /{spec.container_name} container; nothing to migrate.")
        return
    if len(container_ids) != 1:
        raise ContainerConflictError(
            f"expected at most one /{spec.container_name} container, found {len(container_ids)}"
        )

    container_id = container_ids[0]
    action = classify_container(
        _inspect(container_id),
        spec,
        current_project=current_project,
        legacy_projects=legacy_projects,
    )
    if action == "keep":
        print(
            f"Keeping current-project /{spec.container_name} container {container_id[:12]} "
            "for Docker Compose reconciliation."
        )
        return

    print(
        f"Removing verified legacy /{spec.container_name} container {container_id[:12]}; "
        f"named volume {spec.volume_name} is preserved."
    )
    subprocess.run(["docker", "rm", "-f", container_id], check=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Current Compose project name")
    parser.add_argument(
        "--legacy-project",
        action="append",
        default=[],
        help="Recognized legacy Compose project (repeatable)",
    )
    parser.add_argument("services", nargs="+", choices=sorted(SERVICE_SPECS))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        for service in args.services:
            reconcile_service(
                service,
                current_project=args.project,
                legacy_projects=set(args.legacy_project),
            )
    except (ContainerConflictError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Refusing unsafe container-name reconciliation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
