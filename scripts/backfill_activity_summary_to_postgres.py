"""
Backfill ActivitySummary records from Influx into Postgres activities.

Assumptions:
- Source measurement: ActivitySummary_with_run,ingest_run_id=<UUID>
- User: dave0875@gmail.com
- One row per ActivityID

Env vars:
- RUNTRAINER_DATABASE_URL (e.g., postgresql://user:pass@host:5432/runtrainer)
- INFLUXDB_HOST (default: influxdb)
- INFLUXDB_PORT (default: 8086)
- INFLUXDB_USERNAME / INFLUXDB_PASSWORD (required)
- INFLUXDB_DATABASE (default: GarminStats)
- INGEST_RUN_ID (default: 11111111-1111-1111-1111-111111111111)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from influxdb import InfluxDBClient
from sqlalchemy import create_engine, text


DEFAULT_INGEST_RUN_ID = "11111111-1111-1111-1111-111111111111"


def main() -> None:
    db_url = os.environ.get("RUNTRAINER_DATABASE_URL")
    if not db_url:
        raise SystemExit("RUNTRAINER_DATABASE_URL is required")
    influx_user = os.environ.get("INFLUXDB_USERNAME")
    influx_pass = os.environ.get("INFLUXDB_PASSWORD")
    if not influx_user or not influx_pass:
        raise SystemExit("INFLUXDB_USERNAME and INFLUXDB_PASSWORD are required")

    influx_host = os.environ.get("INFLUXDB_HOST", "influxdb")
    influx_port = int(os.environ.get("INFLUXDB_PORT", "8086"))
    influx_db = os.environ.get("INFLUXDB_DATABASE", "GarminStats")
    ingest_run_id = os.environ.get("INGEST_RUN_ID", DEFAULT_INGEST_RUN_ID)

    influx = InfluxDBClient(
        host=influx_host,
        port=influx_port,
        username=influx_user,
        password=influx_pass,
        database=influx_db,
        ssl=False,
        verify_ssl=False,
    )

    engine = create_engine(db_url)

    # Resolve user id for dave0875@gmail.com
    with engine.begin() as conn:
        res = conn.execute(text("SELECT id FROM users WHERE email=:email"), {"email": "dave0875@gmail.com"})
        row = res.fetchone()
        if not row:
            raise SystemExit("User dave0875@gmail.com not found in users")
        user_id = row[0]
        existing = {
            r[0]
            for r in conn.execute(
                text("SELECT fingerprint_hash FROM activities WHERE user_id=:uid"),
                {"uid": str(user_id)},
            )
        }

    measurement = f"ActivitySummary_with_run,ingest_run_id={ingest_run_id}"
    query = f'SELECT * FROM "{measurement}"'
    result = influx.query(query)
    points = list(result.get_points())
    print(f"Fetched {len(points)} points from Influx measurement {measurement}")

    inserted = 0
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for p in points:
            act_id = p.get("ActivityID") or p.get("activityId")
            if act_id is None:
                continue
            fp = str(act_id)
            if fp in existing:
                continue
            start_time = p.get("time")
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else now
            except Exception:
                start_dt = now
            distance = p.get("distance")
            duration = p.get("elapsedDuration") or p.get("duration") or p.get("durationSeconds")
            avg_hr = p.get("averageHR")
            sport = p.get("activityName") or p.get("activityType")
            metadata = {k: v for k, v in p.items() if k not in ("time",)}
            conn.execute(
                text(
                    """
                    INSERT INTO activities
                    (id, user_id, ingest_run_id, start_time, duration_seconds, distance_m, sport,
                     status, fingerprint_hash, metadata, created_at, updated_at)
                    VALUES (:id, :uid, :run_id, :start_time, :duration, :distance, :sport,
                            :status, :fp, CAST(:metadata AS jsonb), :created, :updated)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": str(user_id),
                    "run_id": ingest_run_id,
                    "start_time": start_dt,
                    "duration": int(duration) if duration is not None else None,
                    "distance": float(distance) if distance is not None else None,
                    "sport": sport,
                    "status": "completed",
                    "fp": fp,
                    "metadata": json_dumps(metadata),
                    "created": now,
                    "updated": now,
                },
            )
            inserted += 1
    print(f"Inserted {inserted} activities into Postgres.")


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, default=str)


if __name__ == "__main__":
    main()
