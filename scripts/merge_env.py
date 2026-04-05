#!/usr/bin/env python3
"""Merge one or more dotenv-style files into a single output file."""

from __future__ import annotations

import argparse
from pathlib import Path


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


def main() -> int:
    args = parse_args()
    merged: dict[str, str] = {}
    order: list[str] = []

    for file_name in args.inputs:
        path = Path(file_name)
        if not path.is_file():
            raise SystemExit(f"Missing env file: {path}")
        for key, value in read_env_file(path):
            if key not in merged:
                order.append(key)
            merged[key] = value

    output_path = Path(args.output)
    output_path.write_text(
        "".join(f"{key}={merged[key]}\n" for key in order),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
