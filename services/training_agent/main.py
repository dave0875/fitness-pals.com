"""
Training agent FastAPI service.
- Provides read endpoints for Garmin-derived metrics (InfluxDB v1) secured by Google OAuth.
- Hosts an HTML harness for manual exploration.
- Includes a Google OAuth proxy for GPT Actions.
Note: long lines are tolerated in HTML/queries; Pylint line length is disabled.
"""
# ruff: noqa: E501
# pylint: disable=line-too-long
from __future__ import annotations

import os
from typing import Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from google.oauth2 import id_token
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import auth as auth_module
from . import metrics_routes as metrics_module
from .auth import GOOGLE_CLIENT_ID, router as auth_router
from .influx_utils import (
    get_influx_client,
    get_average_cadence,
    get_elevation_gain,
    get_elevation_stats,
    get_temperature_stats,
    get_max_cadence,
    resolve_cadence,
    first_non_null,
)
from .middleware import REQUEST_COUNTER, REQUEST_LATENCY, metrics_middleware
from .ui import router as ui_router

verify_google_bearer = auth_module.verify_google_bearer

def require_google_auth(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict:
    """Dependency to enforce a valid Google bearer token on protected endpoints."""
    client_id = (
        GOOGLE_CLIENT_ID
        or os.environ.get("RUNTRAINER_GOOGLE_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
    )
    if not client_id:
        raise HTTPException(status_code=500, detail="Server missing RUNTRAINER_GOOGLE_CLIENT_ID env")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_google_bearer(token, client_id)


app = FastAPI(title="Garmin Training API", version="0.1.0")
app.middleware("http")(metrics_middleware)
app.include_router(ui_router)
app.include_router(auth_router)
app.include_router(metrics_module.router)

# Allow metrics routes to rely on overridable helpers from this module (dynamic lookup for tests).
metrics_module.get_influx_client = lambda: get_influx_client()
metrics_module.get_average_cadence = lambda client, row: get_average_cadence(client, row)
metrics_module.get_elevation_gain = lambda client, activity_id: get_elevation_gain(client, activity_id)
metrics_module.get_elevation_stats = lambda client, activity_id: get_elevation_stats(client, activity_id)
metrics_module.get_temperature_stats = lambda client, activity_id: get_temperature_stats(client, activity_id)
metrics_module.get_max_cadence = lambda client, activity_id: get_max_cadence(client, activity_id)


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health_check():
    """Liveness endpoint for health probes."""
    return {"status": "ok"}


__all__ = [
    "app",
    "verify_google_bearer",
    "require_google_auth",
    "GOOGLE_CLIENT_ID",
    "id_token",
    "requests",
    "REQUEST_COUNTER",
    "REQUEST_LATENCY",
    "get_influx_client",
    "get_average_cadence",
    "get_elevation_gain",
    "get_elevation_stats",
    "get_temperature_stats",
    "get_max_cadence",
    "resolve_cadence",
    "first_non_null",
]
