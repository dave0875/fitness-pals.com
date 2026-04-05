#!/usr/bin/env python3
"""Read a single key from a dotenv-style file."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read one value from a dotenv file.")
    parser.add_argument("env_file", help="Path to the dotenv file.")
    parser.add_argument("key", help="Key to read.")
    parser.add_argument(
        "--default",
        default="",
        help="Default value to print when the key is missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)
    values: dict[str, str] = {}

    for raw_line in env_path.read_text().splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()

    print(values.get(args.key, args.default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
