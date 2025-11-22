"""Helpers for querying user-specific InfluxDB connections."""

from __future__ import annotations

import os
from typing import Optional

from influxdb_client import InfluxDBClient
from sqlalchemy.orm import Session

from app.models import DataSource
from app.utils.security import decrypt_token, encrypt_token


def get_user_datasource(db: Session, user_id) -> Optional[DataSource]:
    """Fetch a user's Influx datasource definition."""
    return (
        db.query(DataSource)
        .filter(DataSource.user_id == user_id, DataSource.type == "influxdb")
        .first()
    )


def get_influx_client_for_user(db: Session, user_id) -> InfluxDBClient:
    """Instantiate an Influx client using the stored encrypted token."""
    ds = get_user_datasource(db, user_id)
    if not ds:
        raise ValueError("User has no InfluxDB datasource")
    token = decrypt_token(ds.token_encrypted)
    client = InfluxDBClient(url=ds.influx_url, org=ds.influx_org, token=token)
    # Stash defaults for writers
    client.default_bucket = ds.influx_bucket
    return client


def ensure_user_datasource(db: Session, user_id) -> None:
    """Ensure a datasource row exists for the user using global defaults."""
    if get_user_datasource(db, user_id):
        return
    influx_url = os.environ.get("RUNTRAINER_INFLUX_DEFAULT_URL") or os.environ.get("INFLUXDB_URL") or "http://influxdb:8086"
    influx_org = os.environ.get("INFLUXDB_ORG") or "default"
    influx_bucket = os.environ.get("INFLUXDB_DATABASE") or "GarminStats"
    token_value = os.environ.get("INFLUXDB_TOKEN") or os.environ.get("INFLUXDB_PASSWORD") or ""
    ds = DataSource(
        user_id=user_id,
        type="influxdb",
        influx_url=influx_url,
        influx_org=influx_org,
        influx_bucket=influx_bucket,
        token_encrypted=encrypt_token(token_value),
    )
    db.add(ds)
    db.commit()
