"""On-demand batch trigger for Garmin ingestion."""

from __future__ import annotations

import os
import threading
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import UserProviderToken
from app.db import SESSION_FACTORY
from app.services.sync_jobs import enqueue_sync_job


def fetch_all(db: Session) -> dict:
    """Iterate over all users with Garmin tokens and trigger ingestion."""
    queued = 0
    errors = 0
    provider_key = "garmin" if (os.environ.get("GARMIN_MODE") or "scraper").lower() == "oauth" else "garmin_scraper"
    tokens = db.query(UserProviderToken).filter(UserProviderToken.provider == provider_key).all()
    for token in tokens:
        try:
            user_id = UUID(str(token.user_id))
            enqueue_sync_job(
                db,
                user_id=user_id,
                provider="garmin",
                trigger="scheduler",
            )
            queued += 1
        except HTTPException:
            errors += 1
        except Exception:
            errors += 1
    return {"status": "queued", "queued": queued, "errors": errors}


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
