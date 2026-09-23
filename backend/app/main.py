"""FastAPI application wiring for Run Trainer backend."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.oauth import router as auth_router
from app.routes.metrics import router as metrics_router
from app.routes.chat import router as chat_router
from app.routes import auth_status, providers as provider_router
from app.routes.onboarding import router as onboarding_router
from app.routes.athlete_home import router as athlete_home_router
from app.routes.journey import router as journey_router
from app.routes.dossiers import router as dossiers_router
from app.routes import providers_garmin
from app.routes.ingest import router as ingest_router
from app.routes.archive_imports import router as archive_imports_router
from app.routes.today_plan import router as today_plan_router
from app.routes.intelligence import router as intelligence_router
from app.routes.ux_events import router as ux_events_router
from app.config import get_settings
from app.db import engine


settings = get_settings()
app = FastAPI(title="Run Trainer", debug=settings.debug)

REQUIRED_TABLES = (
    "users",
    "data_sources",
    "provider_apps",
    "user_provider_tokens",
    "dossier_jobs",
    "dossier_artifacts",
    "archive_import_jobs",
    "archive_import_objects",
    "refresh_token_sessions",
    "athlete_goals",
    "next_session_plans",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret,
    same_site="lax",
    https_only=not settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(metrics_router)
app.include_router(chat_router)
app.include_router(provider_router.router)
app.include_router(providers_garmin.router)
app.include_router(auth_status.router)
app.include_router(onboarding_router)
app.include_router(athlete_home_router)
app.include_router(journey_router)
app.include_router(dossiers_router)
app.include_router(ingest_router)
app.include_router(archive_imports_router)
app.include_router(today_plan_router)
app.include_router(intelligence_router)
app.include_router(ux_events_router)


@app.get("/health")
def health():
    """Lightweight health probe for container orchestration."""
    return {"status": "ok"}


def check_backend_ready() -> tuple[bool, dict[str, Any]]:
    """Verify database connectivity and required schema availability."""
    checks: dict[str, Any] = {"database": "unknown", "schema": "unknown"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
            inspector = inspect(conn)
            missing_tables = [name for name in REQUIRED_TABLES if not inspector.has_table(name)]
    except (SQLAlchemyError, Exception) as exc:  # pylint: disable=broad-except
        checks["database"] = f"error: {type(exc).__name__}"
        return False, checks

    if missing_tables:
        checks["schema"] = {"missing_tables": missing_tables}
        return False, checks

    checks["schema"] = "ok"
    return True, checks


@app.get("/ready")
def ready():
    """Readiness probe that verifies core backend dependencies."""
    is_ready, checks = check_backend_ready()
    status_code = 200 if is_ready else 503
    status_text = "ok" if is_ready else "degraded"
    return JSONResponse(status_code=status_code, content={"status": status_text, "checks": checks})


@app.get("/api/health-check")
def api_health_check():
    """API-scoped health probe (mirrors /health)."""
    return {"status": "ok"}
# trigger ci
 
