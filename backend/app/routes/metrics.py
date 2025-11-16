from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.services.influx import get_influx_client_for_user, get_user_datasource
from app.models import User


class RaceReadinessRequest(BaseModel):
    race_type: str
    race_date: datetime


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _query(client, org: str, query: str):
    return client.query_api().query(org=org, query=query)


def _sum_distance(points) -> float:
    total = 0.0
    for table in points:
        for record in table.records:
            total += float(record.get_value() or 0)
    return total


@router.post("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    client = get_influx_client_for_user(db, user.id)
    org = ds.influx_org
    bucket = ds.influx_bucket
    query_api = client.query_api()

    def mileage(days: int):
        q = f'from(bucket: "{bucket}") |> range(start: -{days}d) |> filter(fn: (r) => r._measurement == "ActivitySummary" and r._field == "distance") |> sum()'
        return _sum_distance(query_api.query(org=org, query=q))

    mileage_30 = mileage(30)
    mileage_60 = mileage(60)
    mileage_90 = mileage(90)
    avg_weekly = mileage_90 / 12 if mileage_90 else 0

    hrv_q = f'from(bucket: "{bucket}") |> range(start: -30d) |> filter(fn: (r) => r._measurement == "SleepSummary" and r._field == "avgOvernightHrv") |> mean()'
    hrv = query_api.query(org=org, query=hrv_q)
    hrv_value = None
    for table in hrv:
        for record in table.records:
            hrv_value = record.get_value()

    pace_hist_q = f'from(bucket: "{bucket}") |> range(start: -60d) |> filter(fn: (r) => r._measurement == "ActivitySummary" and r._field == "averageSpeed") |> histogram(bins:[1.5,2.0,2.5,3.0,3.5,4.0], normalize:true)'
    pace_hist = query_api.query(org=org, query=pace_hist_q)
    hist = []
    for table in pace_hist:
        for record in table.records:
            hist.append({"le": record.values.get("le"), "value": record.get_value()})

    long_run_q = f'from(bucket: "{bucket}") |> range(start: -90d) |> filter(fn: (r) => r._measurement == "ActivitySummary" and r._field == "distance") |> max()'
    lr = query_api.query(org=org, query=long_run_q)
    long_run = None
    for table in lr:
        for record in table.records:
            long_run = record.get_value()

    training_load_q = f'from(bucket: "{bucket}") |> range(start: -30d) |> filter(fn: (r) => r._measurement == "TrainingStatus" and r._field =~ /load/) |> mean()'
    tl = query_api.query(org=org, query=training_load_q)
    training_load = []
    for table in tl:
        for record in table.records:
            training_load.append({"field": record.get_field(), "value": record.get_value()})

    return {
        "mileage": {"30d": mileage_30, "60d": mileage_60, "90d": mileage_90},
        "average_weekly_mileage": avg_weekly,
        "long_run_max": long_run,
        "hrv_avg": hrv_value,
        "pace_histogram": hist,
        "training_load": training_load,
    }


@router.post("/race_readiness")
def race_readiness(body: RaceReadinessRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Simple heuristic placeholder
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    client = get_influx_client_for_user(db, user.id)
    org = ds.influx_org
    bucket = ds.influx_bucket
    miles_30 = _sum_distance(
        _query(
            client,
            org,
            f'from(bucket: "{bucket}") |> range(start: -30d) |> filter(fn: (r) => r._measurement == "ActivitySummary" and r._field == "distance") |> sum()',
        )
    )
    readiness = min(100, max(0, miles_30 / 400 * 100))
    commentary = f"Based on {miles_30/1609.34:.1f} miles in last 30d, your readiness for a {body.race_type} looks {readiness:.0f}/100."
    return {"readiness": readiness, "commentary": commentary}
