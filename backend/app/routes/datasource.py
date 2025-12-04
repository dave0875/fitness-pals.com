"""Endpoints for connecting/verifying a user's Influx data source."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from influxdb_client.client.exceptions import InfluxDBError
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import DataSource
from app.types import CurrentUserLike, InfluxClientLike
from app.services.influx import (
    assert_safe_influx_config,
    get_influx_client_for_user,
    get_user_datasource,
    validate_influx_identifier,
)
from app.utils.security import encrypt_token


class InfluxConnectRequest(BaseModel):
    """Request payload for storing Influx credentials."""

    url: HttpUrl
    org: str
    bucket: str
    token: str

    @field_validator("org", "bucket")
    @classmethod
    def validate_identifier(cls, value: str, info):  # type: ignore[override]
        """Reject unsafe Flux identifiers to avoid injection."""
        return validate_influx_identifier(value, info.field_name)


router = APIRouter(prefix="/api/datasource", tags=["datasource"])
logger = logging.getLogger("routes.datasource")


@router.post("/influx/connect")
def connect_influx(
    body: InfluxConnectRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Encrypt and persist Influx credentials for the authenticated user."""
    existing = get_user_datasource(db, user.id)
    encrypted = encrypt_token(body.token)
    logger.info(
        "storing influx datasource",
        extra={"user_id": str(user.id), "url": str(body.url), "org": body.org, "bucket": body.bucket},
    )
    if existing:
        existing.influx_url = str(body.url)  # type: ignore[assignment]
        existing.influx_org = body.org  # type: ignore[assignment]
        existing.influx_bucket = body.bucket  # type: ignore[assignment]
        existing.token_encrypted = encrypted  # type: ignore[assignment]
    else:
        ds = DataSource(
            user_id=user.id,
            type="influxdb",
            influx_url=str(body.url),
            influx_org=body.org,
            influx_bucket=body.bucket,
            token_encrypted=encrypted,
        )
        db.add(ds)
    db.commit()
    return {"status": "ok"}


@router.get("/influx/verify")
def verify_influx(
    user: CurrentUserLike = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Ensure a stored Influx connection is still usable."""
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    try:
        assert_safe_influx_config(ds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    client: InfluxClientLike = get_influx_client_for_user(db, user.id)
    query_api = client.query_api()
    try:
        query_api.query(
            org=ds.influx_org,
            query='import "influxdata/influxdb/schema"\nschema.measurements()',
        )
    except (InfluxDBError, ValueError) as exc:
        message = f"Failed to query InfluxDB: {exc}"
        raise HTTPException(status_code=400, detail=message) from exc
    return {"status": "ok"}
