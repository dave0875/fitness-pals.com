"""Insight endpoints backed by Influx metrics."""

from __future__ import annotations

from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.services.influx import (
    assert_safe_influx_config,
    get_influx_client_for_user,
    get_user_datasource,
)
from app.services.activity_summary import build_canonical_summary
from app.types import CurrentUserLike, InfluxClientLike, InfluxQueryApiLike


class RaceReadinessRequest(BaseModel):
    """Payload describing an upcoming race for readiness scoring."""

    race_type: str
    race_date: datetime


router = APIRouter(prefix="/api/metrics", tags=["metrics"])
logger = logging.getLogger("routes.metrics")


def _query(client: InfluxClientLike, org: str, query: str):
    """Run a Flux query."""
    return client.query_api().query(org=org, query=query)


def _sum_distance(points) -> float:
    """Sum the distance values from a Flux response."""
    total = 0.0
    for table in points:
        for record in table.records:
            total += float(record.get_value() or 0)
    return total


def _distance_sum(
    query_api: InfluxQueryApiLike, org: str, bucket: str, days: int
) -> float:
    """Aggregate distance for the specified window."""
    query = (
        f'from(bucket: "{bucket}") |> range(start: -{days}d) |> '
        'filter(fn: (r) => r._measurement == "ActivitySummary" and '
        'r._field == "distance") |> sum()'
    )
    try:
        return _sum_distance(query_api.query(org=org, query=query))
    except Exception as exc:
        logger.warning("distance query failed", extra={"days": days, "error": str(exc)})
        return 0.0


def _fetch_scalar(query_api: InfluxQueryApiLike, org: str, query: str):
    """Return the first scalar result from a Flux query."""
    try:
        result = query_api.query(org=org, query=query)
    except Exception as exc:
        logger.warning("scalar query failed", extra={"error": str(exc)})
        return None
    for table in result:
        for record in table.records:
            return record.get_value()
    return None


def _fetch_histogram(query_api: InfluxQueryApiLike, org: str, query: str):
    """Return histogram-style results."""
    try:
        response = query_api.query(org=org, query=query)
    except Exception as exc:
        logger.warning("histogram query failed", extra={"error": str(exc)})
        return []
    histogram = []
    for table in response:
        for record in table.records:
            histogram.append(
                {"le": record.values.get("le"), "value": record.get_value()}
            )
    return histogram


def _fetch_training_load(query_api: InfluxQueryApiLike, org: str, query: str):
    """Return load metrics keyed by field name."""
    try:
        response = query_api.query(org=org, query=query)
    except Exception as exc:
        logger.warning("training load query failed", extra={"error": str(exc)})
        return []
    load = []
    for table in response:
        for record in table.records:
            load.append({"field": record.get_field(), "value": record.get_value()})
    return load


@router.post("/summary")
def summary(
    user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Aggregate several readiness metrics from the user's Influx data."""
    ds = get_user_datasource(db, user.id)
    if not ds:
        return build_canonical_summary(db, user.id)
    try:
        assert_safe_influx_config(ds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    client: InfluxClientLike = get_influx_client_for_user(db, user.id)
    org = str(ds.influx_org)
    bucket = str(ds.influx_bucket)
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
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Heuristic readiness estimate based on last 30 days of mileage."""
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    try:
        assert_safe_influx_config(ds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    client = get_influx_client_for_user(db, user.id)
    org = str(ds.influx_org)
    bucket = str(ds.influx_bucket)
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
        f"Based on {miles_30 / 1609.34:.1f} miles in last 30d, your readiness for a {body.race_type} "
        f"looks {readiness:.0f}/100."
    )
    return {"readiness": readiness, "commentary": commentary}
