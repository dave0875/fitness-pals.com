"""On-demand batch trigger for Garmin ingestion."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import UserProviderToken
from app.services.garmin_ingest import fetch_garmin_recent


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
