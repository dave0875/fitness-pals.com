#!/usr/bin/env python3
"""Merge one or more dotenv-style files into a single output file."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge dotenv files. Later files override earlier keys."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the merged output file.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Input dotenv files to merge in order.",
    )
    return parser.parse_args()


def read_env_file(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        entries.append((key.strip(), value))
    return entries


def _derive_runtrainer_postgres_env(values: dict[str, str]) -> list[tuple[str, str]]:
    database_url = values.get("RUNTRAINER_DATABASE_URL", "").strip()
    if not database_url:
        return []

    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgresql"):
        return []

    derived: list[tuple[str, str]] = []
    if "RUNTRAINER_POSTGRES_USER" not in values and parsed.username:
        derived.append(("RUNTRAINER_POSTGRES_USER", unquote(parsed.username)))
    if "RUNTRAINER_POSTGRES_PASSWORD" not in values and parsed.password:
        derived.append(("RUNTRAINER_POSTGRES_PASSWORD", unquote(parsed.password)))
    database_name = parsed.path.lstrip("/")
    if "RUNTRAINER_POSTGRES_DB" not in values and database_name:
        derived.append(("RUNTRAINER_POSTGRES_DB", unquote(database_name)))
    return derived


def merge_env_files(output_path: Path, inputs: list[Path]) -> None:
    merged: dict[str, str] = {}
    order: list[str] = []

    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"Missing env file: {path}")
        for key, value in read_env_file(path):
            if key not in merged:
                order.append(key)
            merged[key] = value

    for key, value in _derive_runtrainer_postgres_env(merged):
        if key not in merged:
            order.append(key)
            merged[key] = value

    output_path.write_text(
        "".join(f"{key}={merged[key]}\n" for key in order),
    )


def main() -> int:
    args = parse_args()
    merge_env_files(Path(args.output), [Path(file_name) for file_name in args.inputs])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
