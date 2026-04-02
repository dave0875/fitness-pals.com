"""On-demand batch trigger for Garmin ingestion."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import UserProviderToken
from app.db import SESSION_FACTORY
from app.types import CurrentUserLike
from app.services.sync_jobs import run_garmin_sync_job


@dataclass
class _UserCtx:
    """Lightweight user protocol implementation for scheduler."""

    id: Any
    tenant_id: Any = None


def fetch_all(db: Session) -> dict:
    """Iterate over all users with Garmin tokens and trigger ingestion."""
    runs = 0
    errors = 0
    provider_key = "garmin" if (os.environ.get("GARMIN_MODE") or "oauth").lower() == "oauth" else "garmin_scraper"
    tokens = db.query(UserProviderToken).filter(UserProviderToken.provider == provider_key).all()
    for token in tokens:
        try:
            user_ctx = _UserCtx(id=token.user_id, tenant_id=getattr(token, "tenant_id", None))
            run = run_garmin_sync_job(db, user=user_ctx, trigger="scheduler").ingest_run
            runs += 1 if run else 0
        except HTTPException:
            errors += 1
        except Exception:
            errors += 1
    return {"status": "ok", "runs": runs, "errors": errors}


def start_polling(interval_seconds: int = 300):
    """Poll for new data every interval_seconds."""
    def _loop():
        while True:
            session = SESSION_FACTORY()
            try:
                fetch_all(session)
            finally:
                session.close()
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
