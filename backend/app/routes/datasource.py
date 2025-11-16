from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import DataSource, User
from app.services.influx import get_influx_client_for_user, get_user_datasource
from app.utils.security import encrypt_token, decrypt_token


class InfluxConnectRequest(BaseModel):
    url: HttpUrl
    org: str
    bucket: str
    token: str


router = APIRouter(prefix="/api/datasource", tags=["datasource"])


@router.post("/influx/connect")
def connect_influx(body: InfluxConnectRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = get_user_datasource(db, user.id)
    encrypted = encrypt_token(body.token)
    if existing:
        existing.influx_url = str(body.url)
        existing.influx_org = body.org
        existing.influx_bucket = body.bucket
        existing.token_encrypted = encrypted
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
def verify_influx(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = get_user_datasource(db, user.id)
    if not ds:
        raise HTTPException(status_code=404, detail="No datasource configured")
    client = get_influx_client_for_user(db, user.id)
    query_api = client.query_api()
    try:
        query_api.query(org=ds.influx_org, query='import "influxdata/influxdb/schema"\nschema.measurements()')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to query InfluxDB: {e}")
    return {"status": "ok"}
