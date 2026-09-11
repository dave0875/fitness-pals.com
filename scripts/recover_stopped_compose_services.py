#!/usr/bin/env python3
"""Start stopped Compose services without replacing their release images."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Sequence


CommandRunner = Callable[[list[str]], str]
ACTIVE_STATES = {"running", "restarting"}


def run_command(command: list[str]) -> str:
    """Run a command and return its standard output."""
    result = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def reconcile_services(
    services: Sequence[str],
    *,
    env_file: str,
    run: CommandRunner = run_command,
) -> None:
    """Start stopped service containers and create services that are absent."""
    compose = ["docker", "compose", "--env-file", env_file]
    for service in services:
        container_ids = [
            container_id
            for container_id in run(
                [*compose, "ps", "-a", "-q", service]
            ).splitlines()
            if container_id
        ]
        if not container_ids:
            print(f"{service} has no container; creating it.")
            run([*compose, "up", "-d", "--no-deps", service])
            continue

        for container_id in container_ids:
            status = run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}}",
                    container_id,
                ]
            ).strip()
            if status in ACTIVE_STATES:
                continue
            print(
                f"Starting stopped {service} container {container_id} "
                f"(status: {status})."
            )
            run(["docker", "start", container_id])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover stopped Compose services without recreating them."
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument("services", nargs="+")
    args = parser.parse_args()

    reconcile_services(args.services, env_file=args.env_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
