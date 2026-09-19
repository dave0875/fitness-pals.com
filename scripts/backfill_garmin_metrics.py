"""Backfill dated Garmin performance-metric exports to account-tagged Influx.

Dry-run by default. Original JSON rows are retained as a string field alongside
typed scalar fields; no relational metric table currently exists in the app.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID


FILENAME = re.compile(r"^(?P<kind>[A-Za-z0-9]+)_.*_(?P<profile>\d+)\.json$")


def _metric_day(row: dict[str, Any]) -> date:
    raw = row.get("calendarDate") or row.get("timestampGmt")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        day = datetime.fromtimestamp(float(raw) / 1000, timezone.utc).date()
    elif isinstance(raw, str):
        day = date.fromisoformat(raw[:10])
    else:
        raise ValueError("Metric row has no usable date")
    if day.year < 2000 or day > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValueError("Metric date is outside the expected range")
    return day


def _fields(row: dict[str, Any], index: int) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "source_row_index": index,
        "payload_json": json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False),
    }
    for key, value in row.items():
        safe_key = re.sub(r"[^A-Za-z0-9_]", "_", key)
        if isinstance(value, bool):
            fields[f"b_{safe_key}"] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            fields[f"n_{safe_key}"] = float(value)
        elif isinstance(value, str) and len(value) <= 4096:
            fields[f"s_{safe_key}"] = value
    return fields


def load_metric_points(directory: Path, profile_id: int, user_id: UUID) -> tuple[list[dict[str, Any]], Counter[str]]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("No Garmin metric JSON files were staged")
    points: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for path in paths:
        match = FILENAME.fullmatch(path.name)
        if match is None or int(match["profile"]) != profile_id:
            raise ValueError(f"Unexpected Garmin metric file: {path.name}")
        kind = match["kind"]
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError(f"Garmin metric file must contain a list: {path.name}")
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                raise ValueError(f"Malformed row in {path.name}")
            row_profile = row.get("userProfilePK", row.get("userProfilePk"))
            if row_profile is not None and str(row_profile) != str(profile_id):
                raise ValueError(f"Garmin profile mismatch in {path.name}")
            day = _metric_day(row)
            # Index-based microseconds preserve multiple entries on the same day
            # without turning every record into a separate Influx series.
            timestamp = datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(microseconds=index)
            points.append({
                "measurement": f"FitnessPalsGarminMetric{kind}",
                "time": timestamp,
                "tags": {
                    "user_id": str(user_id),
                    "profile_id": str(profile_id),
                    "source_file": path.name,
                },
                "fields": _fields(row, index),
            })
            counts[kind] += 1
    return points, counts


def _verify_account(email: str, user_id: UUID) -> None:
    from sqlalchemy import func
    from app.db import SESSION_FACTORY
    from app.models import User

    db = SESSION_FACTORY()
    try:
        user = db.query(User).filter(func.lower(User.email) == email.lower()).one_or_none()
        if user is None or user.id != user_id:
            raise ValueError("Production account does not match expected email and UUID")
    finally:
        db.close()


def _write_influx(points: list[dict[str, Any]]) -> None:
    from influxdb_client import InfluxDBClient
    from influxdb_client.client.write_api import SYNCHRONOUS

    url = os.environ.get("RUNTRAINER_INFLUX_URL") or "http://influxdb:8086"
    bucket = os.environ.get("INFLUXDB_DATABASE") or "GarminStats"
    org = os.environ.get("INFLUXDB_ORG") or "default"
    token = os.environ.get("INFLUXDB_TOKEN") or os.environ.get("INFLUXDB_PASSWORD")
    if not token:
        raise ValueError("Production Influx credentials are unavailable")
    client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)
    try:
        writer = client.write_api(write_options=SYNCHRONOUS)
        try:
            for index in range(0, len(points), 250):
                writer.write(bucket=bucket, org=org, record=points[index:index + 250])
        finally:
            writer.close()
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--expected-user-id", type=UUID, required=True)
    parser.add_argument("--expected-profile-id", type=int, required=True)
    parser.add_argument("--expected-files", type=int, required=True)
    parser.add_argument("--expected-records", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    files = list(args.directory.glob("*.json"))
    points, counts = load_metric_points(args.directory, args.expected_profile_id, args.expected_user_id)
    if len(files) != args.expected_files or len(points) != args.expected_records:
        raise SystemExit("Metric file or record counts differ from preflight; no writes performed")
    print(json.dumps({
        "mode": "apply" if args.apply else "dry_run",
        "files": len(files), "records": len(points), "by_type": dict(counts),
        "user_id": str(args.expected_user_id), "profile_id": args.expected_profile_id,
    }, sort_keys=True), flush=True)
    if args.apply:
        _verify_account(args.email, args.expected_user_id)
        _write_influx(points)
        print(json.dumps({"influx_metric_points": len(points)}), flush=True)


if __name__ == "__main__":
    main()
