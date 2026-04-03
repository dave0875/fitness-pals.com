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

from typing import Any, cast

import requests  # type: ignore[import-untyped]
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, Response
from google.oauth2 import id_token
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from services.training_agent import auth as auth_module
from services.training_agent import metrics_routes as metrics_module
from services.training_agent.auth import GOOGLE_CLIENT_ID, require_google_auth, router as auth_router
from services.training_agent.influx_utils import (
    get_influx_client,
    get_average_cadence,
    get_elevation_gain,
    get_elevation_stats,
    get_temperature_stats,
    get_max_cadence,
    resolve_cadence,
    first_non_null,
)
from services.training_agent.middleware import REQUEST_COUNTER, REQUEST_LATENCY, metrics_middleware
from services.training_agent.ui import router as ui_router

verify_google_bearer = auth_module.verify_google_bearer


app = FastAPI(title="Garmin Training API", version="0.1.0")
app.middleware("http")(metrics_middleware)
app.include_router(ui_router)
app.include_router(auth_router)
app.include_router(metrics_module.router, dependencies=[Depends(require_google_auth)])

# Allow metrics routes to rely on overridable helpers from this module (dynamic lookup for tests).
# pylint: disable=unnecessary-lambda
metrics_module_typed = cast(Any, metrics_module)
metrics_module_typed.get_influx_client = lambda: get_influx_client()
metrics_module_typed.get_average_cadence = lambda client, row: get_average_cadence(client, row)
metrics_module_typed.get_elevation_gain = lambda client, activity_id: get_elevation_gain(client, activity_id)
metrics_module_typed.get_elevation_stats = lambda client, activity_id: get_elevation_stats(client, activity_id)
metrics_module_typed.get_temperature_stats = lambda client, activity_id: get_temperature_stats(client, activity_id)
metrics_module_typed.get_max_cadence = lambda client, activity_id: get_max_cadence(client, activity_id)
# pylint: enable=unnecessary-lambda


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health_check():
    """Liveness endpoint for health probes."""
    return {"status": "ok"}


def check_training_agent_ready() -> tuple[bool, dict[str, str]]:
    """Verify the training agent can reach its Influx dependency."""
    client = None
    try:
        client = get_influx_client()
        client.ping()
        client.query("SHOW DATABASES")
    except (
        InfluxDBClientError,
        InfluxDBServerError,
        OSError,
        ValueError,
        Exception,
    ) as exc:  # pylint: disable=broad-except
        return False, {"influxdb": f"error: {type(exc).__name__}"}
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return True, {"influxdb": "ok"}


@app.get("/ready")
def ready_check():
    """Readiness probe that verifies the Influx dependency."""
    is_ready, checks = check_training_agent_ready()
    status_code = 200 if is_ready else 503
    status_text = "ok" if is_ready else "degraded"
    return JSONResponse(status_code=status_code, content={"status": status_text, "checks": checks})


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
