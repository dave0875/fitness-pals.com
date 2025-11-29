"""On-demand batch trigger for Garmin ingestion."""

from __future__ import annotations

from types import SimpleNamespace
import threading
import time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import UserProviderToken
from app.services.garmin_ingest import fetch_garmin_recent
from app.db import SESSION_FACTORY


def fetch_all(db: Session) -> dict:
    """Iterate over all users with Garmin tokens and trigger ingestion."""
    runs = 0
    errors = 0
    tokens = db.query(UserProviderToken).filter(UserProviderToken.provider == "garmin").all()
    for token in tokens:
        try:
            user_ctx = SimpleNamespace(id=token.user_id, tenant_id=getattr(token, "tenant_id", None))
            run = fetch_garmin_recent(db, user_ctx)
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
