"""Helpers for querying user-specific InfluxDB connections."""

from __future__ import annotations

from typing import Optional

from influxdb_client import InfluxDBClient
from sqlalchemy.orm import Session

from app.models import DataSource
from app.utils.security import decrypt_token


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
    return InfluxDBClient(url=ds.influx_url, org=ds.influx_org, token=token)
