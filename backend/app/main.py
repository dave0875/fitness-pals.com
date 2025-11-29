"""FastAPI application wiring for Run Trainer backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.oauth import router as auth_router
from app.routes.datasource import router as datasource_router
from app.routes.metrics import router as metrics_router
from app.routes.chat import router as chat_router
from app.routes import auth_status, providers as provider_router
from app.routes import providers_garmin
from app.routes.ingest import router as ingest_router
from app.config import get_settings


settings = get_settings()
app = FastAPI(title="Run Trainer", debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(datasource_router)
app.include_router(metrics_router)
app.include_router(chat_router)
app.include_router(provider_router.router)
app.include_router(providers_garmin.router)
app.include_router(auth_status.router)
app.include_router(ingest_router)


@app.get("/health")
def health():
    """Lightweight health probe for container orchestration."""
    return {"status": "ok"}


@app.get("/api/health-check")
def api_health_check():
    """API-scoped health probe (mirrors /health)."""
    return {"status": "ok"}
