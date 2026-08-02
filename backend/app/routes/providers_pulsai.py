"""Authenticated PulsAI MCP connection, status, and sync endpoints."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.services.providers import (
    ProviderTokenDetails,
    get_user_provider_token,
    save_user_provider_token,
)
from app.services.sync_jobs import enqueue_sync_job, get_sync_checkpoint
from app.types import CurrentUserLike


router = APIRouter(prefix="/api/providers/pulsai", tags=["pulsai"])


class PulsaiConnectionRequest(BaseModel):
    """Private per-athlete PulsAI MCP endpoint registration."""

    endpoint: SecretStr
    pulsai_user_id: str | None = None


def _allowed_hosts() -> set[str]:
    configured = os.environ.get("RUNTRAINER_PULSAI_ALLOWED_HOSTS", "pulsai.me")
    return {host.strip().lower() for host in configured.split(",") if host.strip()}


def _validated_endpoint(secret: SecretStr) -> tuple[str, str]:
    endpoint = secret.get_secret_value().strip()
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    allowed = _allowed_hosts()
    host_allowed = any(host == base or host.endswith(f".{base}") for base in allowed)
    if (
        parsed.scheme != "https"
        or not host_allowed
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise HTTPException(status_code=400, detail="Invalid PulsAI MCP endpoint")
    return endpoint, host


@router.post("/connection")
def connect_pulsai(
    body: PulsaiConnectionRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Encrypt and store the authenticated athlete's private PulsAI endpoint."""
    endpoint, host = _validated_endpoint(body.endpoint)
    save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            tenant_id=getattr(user, "tenant_id", None),
            provider="pulsai",
            access_token=endpoint,
            provider_user_id=body.pulsai_user_id,
            scope="mcp:read",
            metadata={
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "endpoint_host": host,
                "upstream_provider": "garmin",
            },
        ),
    )
    return {"status": "connected", "provider": "pulsai", "endpoint_host": host}


@router.get("/status")
def pulsai_status(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return connection and freshness metadata without exposing the private URL."""
    tenant_id = getattr(user, "tenant_id", None)
    token = get_user_provider_token(db, user.id, "pulsai", tenant_id)
    checkpoint = get_sync_checkpoint(db, user_id=user.id, provider="pulsai")
    metadata = token.metadata_json if token and token.metadata_json else {}
    return {
        "status": "connected" if token else "missing",
        "provider": "pulsai",
        "upstream_provider": "garmin",
        "provider_user_id": token.provider_user_id if token else None,
        "endpoint_host": metadata.get("endpoint_host"),
        "connected_at": metadata.get("connected_at"),
        "sync_status": checkpoint.status if checkpoint else "never_synced",
        "last_synced_at": (
            checkpoint.last_synced_at.isoformat()
            if checkpoint and checkpoint.last_synced_at
            else None
        ),
        "freshness": checkpoint.cursor_json if checkpoint else None,
    }


@router.post("/fetch")
def pulsai_fetch(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
    test_run: bool = False,
):
    """Queue a PulsAI sync for the authenticated athlete."""
    token = get_user_provider_token(
        db, user.id, "pulsai", getattr(user, "tenant_id", None)
    )
    if token is None:
        raise HTTPException(status_code=410, detail="PulsAI connection required")
    job = enqueue_sync_job(
        db,
        user_id=user.id,
        provider="pulsai",
        trigger="manual",
        test_run=test_run,
    )
    return {"status": "queued", "sync_job_id": str(job.id), "test_run": test_run}
