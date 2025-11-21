"""Insight endpoints backed by Influx metrics."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.services.influx import get_influx_client_for_user, get_user_datasource
from app.models import User


class RaceReadinessRequest(BaseModel):
    """Payload describing an upcoming race for readiness scoring."""

    race_type: str
    race_date: datetime


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _query(client, org: str, query: str):
    """Run a Flux query."""
    return client.query_api().query(org=org, query=query)


def _sum_distance(points) -> float:
    """Sum the distance values from a Flux response."""
    total = 0.0
    for table in points:
        for record in table.records:
            total += float(record.get_value() or 0)
    return total


def _distance_sum(query_api, org: str, bucket: str, days: int) -> float:
    """Aggregate distance for the specified window."""
    query = (
        f'from(bucket: "{bucket}") |> range(start: -{days}d) |> '
        'filter(fn: (r) => r._measurement == "ActivitySummary" and '
        'r._field == "distance") |> sum()'
    )
    return _sum_distance(query_api.query(org=org, query=query))


def _fetch_scalar(query_api, org: str, query: str):
    """Return the first scalar result from a Flux query."""
    result = query_api.query(org=org, query=query)
    for table in result:
        for record in table.records:
            return record.get_value()
    return None


def _fetch_histogram(query_api, org: str, query: str):
    """Return histogram-style results."""
    response = query_api.query(org=org, query=query)
    histogram = []
    for table in response:
        for record in table.records:
            histogram.append(
                {"le": record.values.get("le"), "value": record.get_value()}
            )
    return histogram


def _fetch_training_load(query_api, org: str, query: str):
    """Return load metrics keyed by field name."""
    response = query_api.query(org=org, query=query)
    load = []
    for table in response:
        for record in table.records:
            load.append({"field": record.get_field(), "value": record.get_value()})
    return load


@router.post("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Aggregate several readiness metrics from the user's Influx data."""
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    client = get_influx_client_for_user(db, user.id)
    org = ds.influx_org
    bucket = ds.influx_bucket
    query_api = client.query_api()
    mileage_totals = {
        window: _distance_sum(query_api, org, bucket, window) for window in (30, 60, 90)
    }
    avg_weekly = mileage_totals[90] / 12 if mileage_totals[90] else 0

    hrv_value = _fetch_scalar(
        query_api,
        org,
        f'from(bucket: "{bucket}") |> range(start: -30d) |> filter(fn: '
        '(r) => r._measurement == "SleepSummary" and r._field == "avgOvernightHrv") '
        "|> mean()",
    )
    hist = _fetch_histogram(
        query_api,
        org,
        f'from(bucket: "{bucket}") |> range(start: -60d) |> filter(fn: '
        '(r) => r._measurement == "ActivitySummary" and r._field == "averageSpeed") '
        "|> histogram(bins:[1.5,2.0,2.5,3.0,3.5,4.0], normalize:true)",
    )
    long_run = _fetch_scalar(
        query_api,
        org,
        f'from(bucket: "{bucket}") |> range(start: -90d) |> filter(fn: '
        '(r) => r._measurement == "ActivitySummary" and r._field == "distance") '
        "|> max()",
    )
    training_load = _fetch_training_load(
        query_api,
        org,
        f'from(bucket: "{bucket}") |> range(start: -30d) |> filter(fn: '
        '(r) => r._measurement == "TrainingStatus" and r._field =~ /load/) |> mean()',
    )

    return {
        "mileage": {f"{window}d": value for window, value in mileage_totals.items()},
        "average_weekly_mileage": avg_weekly,
        "long_run_max": long_run,
        "hrv_avg": hrv_value,
        "pace_histogram": hist,
        "training_load": training_load,
    }


@router.post("/race_readiness")
def race_readiness(
    body: RaceReadinessRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Heuristic readiness estimate based on last 30 days of mileage."""
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
            (
                f'from(bucket: "{bucket}") |> range(start: -30d) |> '
                'filter(fn: (r) => r._measurement == "ActivitySummary" and '
                'r._field == "distance") |> sum()'
            ),
        )
    )
    readiness = min(100, max(0, miles_30 / 400 * 100))
    commentary = (
        f"Based on {miles_30/1609.34:.1f} miles in last 30d, your readiness for a {body.race_type} "
        f"looks {readiness:.0f}/100."
    )
    return {"readiness": readiness, "commentary": commentary}
