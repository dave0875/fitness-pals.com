#!/usr/bin/env python3
"""Detect compose and service changes between two git revisions."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass


KNOWN_SERVICES = (
    "postgres",
    "influxdb",
    "grafana",
    "cloudflared",
    "frontend",
    "backend",
    "worker",
    "training-agent",
)

SERVICE_ALIASES = {
    "runtrainer-postgres": "postgres",
}

DEPLOYMENT_CONTROL_PATHS = {
    ".github/workflows/ci-cd.yml",
    "scripts/detect_changed_services.py",
    "scripts/smoke_production.py",
}


@dataclass(frozen=True)
class ServiceRange:
    """Line range occupied by a compose service block."""

    name: str
    start: int
    end: int


def git_lines(*args: str) -> list[str]:
    """Run a git command and return stripped output lines."""
    output = subprocess.check_output(["git", *args], text=True)
    return [line for line in output.splitlines() if line]


def parse_service_ranges(text: str) -> list[ServiceRange]:
    """Map top-level compose services to their line ranges."""
    lines = text.splitlines()
    in_services = False
    starts: list[tuple[str, int]] = []
    for lineno, line in enumerate(lines, start=1):
        if line == "services:":
            in_services = True
            continue
        if not in_services:
            continue
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            starts.append((match.group(1), lineno))
    ranges: list[ServiceRange] = []
    for index, (name, start) in enumerate(starts):
        next_start = starts[index + 1][1] if index + 1 < len(starts) else len(lines) + 1
        ranges.append(ServiceRange(name=name, start=start, end=next_start - 1))
    return ranges


def changed_line_numbers(diff_text: str, prefix: str) -> set[int]:
    """Extract changed line numbers from unified diff hunk headers."""
    line_numbers: set[int] = set()
    pattern = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    old_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
    for line in diff_text.splitlines():
        if prefix == "new":
            match = pattern.match(line)
            if not match:
                continue
            start = int(match.group(2))
            count = int(match.group(3) or "1")
        else:
            match = old_pattern.match(line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or "1")
        if count == 0:
            continue
        line_numbers.update(range(start, start + count))
    return line_numbers


def services_for_lines(ranges: list[ServiceRange], line_numbers: set[int]) -> set[str]:
    """Return services whose compose blocks intersect the changed lines."""
    changed = set()
    for service in ranges:
        if any(service.start <= line <= service.end for line in line_numbers):
            changed.add(service.name)
    return changed


def normalize_service_name(name: str) -> str:
    """Collapse compose service aliases into stable workflow names."""
    return SERVICE_ALIASES.get(name, name)


def changed_files(before_sha: str, head_sha: str) -> list[str]:
    """Return changed files for the push range, or all files on first push."""
    if not before_sha or before_sha == ("0" * 40):
        return git_lines("ls-tree", "--name-only", "-r", head_sha)
    return git_lines("diff", "--name-only", before_sha, head_sha)


def detect_compose_services(before_sha: str, head_sha: str) -> set[str]:
    """Return compose services affected by changes inside compose.yml."""
    if not before_sha or before_sha == ("0" * 40):
        return set(KNOWN_SERVICES)
    diff_text = subprocess.check_output(
        ["git", "diff", "--unified=0", before_sha, head_sha, "--", "compose.yml"],
        text=True,
    )
    if not diff_text.strip():
        return set()

    current_compose = open("compose.yml", encoding="utf-8").read()
    previous_compose = subprocess.check_output(
        ["git", "show", f"{before_sha}:compose.yml"],
        text=True,
    )
    new_lines = changed_line_numbers(diff_text, "new")
    old_lines = changed_line_numbers(diff_text, "old")
    changed = services_for_lines(parse_service_ranges(current_compose), new_lines)
    changed.update(services_for_lines(parse_service_ranges(previous_compose), old_lines))
    normalized = {normalize_service_name(service) for service in changed}
    return normalized.intersection(KNOWN_SERVICES)


def write_outputs(path: str, outputs: dict[str, bool]) -> None:
    """Append boolean outputs for GitHub Actions."""
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={'true' if value else 'false'}\n")


def runtime_tree_changed(files: list[str], tree: str) -> bool:
    """Return whether runtime files, rather than tests alone, changed in a tree."""
    prefix = f"{tree}/"
    test_prefix = f"{tree}/tests/"
    return any(path.startswith(prefix) and not path.startswith(test_prefix) for path in files)


def build_outputs(files: list[str], compose_services: set[str]) -> dict[str, bool]:
    """Translate changed files and compose services into workflow outputs."""
    if any(path in DEPLOYMENT_CONTROL_PATHS for path in files):
        return {
            "postgres_changed": True,
            "influxdb_changed": True,
            "grafana_changed": True,
            "cloudflared_changed": True,
            "frontend_changed": True,
            "backend_changed": True,
            "worker_changed": True,
            "training_agent_changed": True,
        }

    normalized_services = {normalize_service_name(service) for service in compose_services}
    return {
        "postgres_changed": "postgres" in normalized_services,
        "influxdb_changed": "influxdb" in normalized_services,
        "grafana_changed": "grafana" in normalized_services,
        "cloudflared_changed": "cloudflared" in normalized_services,
        "frontend_changed": runtime_tree_changed(files, "frontend")
        or "frontend" in normalized_services,
        "backend_changed": runtime_tree_changed(files, "backend")
        or "backend" in normalized_services,
        "worker_changed": runtime_tree_changed(files, "backend")
        or "worker" in normalized_services,
        "training_agent_changed": any(path.startswith("services/") for path in files)
        or "training-agent" in normalized_services,
    }


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()

    files = changed_files(args.before, args.head)
    compose_services = detect_compose_services(args.before, args.head) if "compose.yml" in files else set()
    outputs = build_outputs(files, compose_services)

    print("Changed files:")
    for path in files:
        print(path)
    print("Changed services:")
    for key, value in outputs.items():
        if value:
            print(f"- {key}")

    if args.output:
        write_outputs(args.output, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
