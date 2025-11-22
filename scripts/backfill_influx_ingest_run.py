"""
Backfill a constant ingest_run_id field into Influx measurements.

This script copies points from existing measurements into *_with_run variants,
adding a static ingest_run_id field that matches the fabricated ingest run
seeded in migration 0005_add_user_and_ingest_fk.py.

Usage:
    INFLUX_HOST (default: influxdb)
    INFLUX_DB (default: GarminStats)
    INFLUX_USER / INFLUX_PASS (required)
Run from repo root:
    python scripts/backfill_influx_ingest_run.py
"""

from __future__ import annotations

import os
import subprocess
import sys


INGEST_RUN_ID = "11111111-1111-1111-1111-111111111111"
MEASUREMENTS = [
    "ActivityGPS",
    "ActivityLap",
    "ActivitySession",
    "ActivitySummary",
    "BodyBatteryIntraday",
    "BodyComposition",
    "BreathingRateIntraday",
    "DailyStats",
    "DemoPoint",
    "DeviceSync",
    "EnduranceScore",
    "FitnessAge",
    "HRV_Intraday",
    "HeartRateIntraday",
    "HillScore",
    "LactateThreshold",
    "RacePredictions",
    "SleepIntraday",
    "SleepSummary",
    "SolarIntensity",
    "StepsIntraday",
    "StressIntraday",
    "TrainingReadiness",
    "TrainingStatus",
    "VO2_Max",
]


def run(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr)
    if res.returncode != 0:
        raise SystemExit(res.returncode)


def main() -> None:
    influx_host = os.environ.get("INFLUX_HOST", "influxdb")
    influx_db = os.environ.get("INFLUX_DB", "GarminStats")
    influx_user = os.environ.get("INFLUX_USER")
    influx_pass = os.environ.get("INFLUX_PASS")
    if not influx_user or not influx_pass:
        print("INFLUX_USER and INFLUX_PASS are required", file=sys.stderr)
        raise SystemExit(1)

    for measurement in MEASUREMENTS:
        dest = f"{measurement}_with_run"
        query = (
            f"SELECT *, '{INGEST_RUN_ID}' AS ingest_run_id "
            f"INTO \"{dest}\" FROM \"{measurement}\" GROUP BY *"
        )
        cmd = [
            "influx",
            "-host",
            influx_host,
            "-username",
            influx_user,
            "-password",
            influx_pass,
            "-database",
            influx_db,
            "-execute",
            query,
        ]
        run(cmd)


if __name__ == "__main__":
    main()
