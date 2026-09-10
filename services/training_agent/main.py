"""
Training agent FastAPI service.
- Provides canonical, user-scoped fitness read endpoints secured by OAuth.
- Hosts an HTML harness for manual exploration.
- Includes a Google OAuth proxy for GPT Actions.
Note: long lines are tolerated in HTML/queries; Pylint line length is disabled.
"""
# ruff: noqa: E501
# pylint: disable=line-too-long
from __future__ import annotations

import requests  # type: ignore[import-untyped]
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from google.oauth2 import id_token
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from services.training_agent import auth as auth_module
from services.training_agent import metrics_routes as metrics_module
from services.training_agent.auth import (
    GOOGLE_CLIENT_ID,
    OIDC_CLIENT_ID,
    require_google_auth,
    router as auth_router,
)
from services.training_agent.influx_utils import first_non_null, resolve_cadence
from services.training_agent.middleware import REQUEST_COUNTER, REQUEST_LATENCY, metrics_middleware
from services.training_agent.training_data import check_database_ready
from services.training_agent.ui import router as ui_router

verify_google_bearer = auth_module.verify_google_bearer
verify_bearer = auth_module.verify_bearer


app = FastAPI(title="Garmin Training API", version="0.1.0")
app.middleware("http")(metrics_middleware)
app.include_router(ui_router)
app.include_router(auth_router)
app.include_router(metrics_module.router)


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
    """Verify the training agent can reach canonical Postgres storage."""
    return check_database_ready()


@app.get("/ready")
def ready_check():
    """Readiness probe that verifies the canonical Postgres dependency."""
    is_ready, checks = check_training_agent_ready()
    status_code = 200 if is_ready else 503
    status_text = "ok" if is_ready else "degraded"
    return JSONResponse(status_code=status_code, content={"status": status_text, "checks": checks})


__all__ = [
    "app",
    "OIDC_CLIENT_ID",
    "verify_google_bearer",
    "verify_bearer",
    "require_google_auth",
    "GOOGLE_CLIENT_ID",
    "id_token",
    "requests",
    "REQUEST_COUNTER",
    "REQUEST_LATENCY",
    "resolve_cadence",
    "first_non_null",
]
