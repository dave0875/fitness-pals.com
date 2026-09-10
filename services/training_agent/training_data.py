"""Canonical, user-scoped Postgres access for the training agent."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Iterator

from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .auth import require_google_auth


@dataclass(frozen=True)
class Athlete:
    """The canonical internal identity resolved from verified OAuth claims."""

    id: uuid.UUID
    email: str


def _database_url() -> str:
    value = os.environ.get("RUNTRAINER_DATABASE_URL")
    if not value:
        raise RuntimeError("RUNTRAINER_DATABASE_URL is required")
    return value


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the shared Postgres engine lazily after runtime configuration loads."""
    return create_engine(_database_url(), pool_pre_ping=True, future=True)


def get_db() -> Iterator[Session]:
    """Yield one canonical database session for an HTTP request."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, future=True)
    with factory() as session:
        yield session


def _verified_email(claims: dict[str, Any]) -> str | None:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    verified = claims.get("email_verified", claims.get("verified_email"))
    if verified is False or (isinstance(verified, str) and verified.lower() == "false"):
        return None
    return email.strip().casefold()


def get_current_athlete(
    claims: dict[str, Any] = Depends(require_google_auth),
    db: Session = Depends(get_db),
) -> Athlete:
    """Resolve verified external claims to exactly one canonical internal user."""
    email = _verified_email(claims)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated athlete is not provisioned",
        )
    rows = (
        db.execute(
            text(
                "SELECT id, email FROM users "
                "WHERE lower(email) = :email ORDER BY id LIMIT 2"
            ),
            {"email": email},
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated athlete is not provisioned",
        )
    try:
        athlete_id = uuid.UUID(str(rows[0]["id"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated athlete is not provisioned",
        ) from exc
    return Athlete(id=athlete_id, email=str(rows[0]["email"]))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class CanonicalTrainingStore:
    """Read canonical fitness records with a mandatory user predicate."""

    def __init__(self, db: Session):
        self.db = db

    def activities(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT id, user_id, start_time, duration_seconds, distance_m, sport, "
            "metadata AS metadata_json FROM activities WHERE user_id = :user_id"
        )
        bound_user_id: Any = (
            user_id if self.db.get_bind().dialect.name == "postgresql" else str(user_id)
        )
        params: dict[str, Any] = {"user_id": bound_user_id}
        if since is not None:
            query += " AND start_time >= :since"
            params["since"] = since
        query += " ORDER BY start_time DESC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = max(int(limit), 1)
        rows = self.db.execute(text(query), params).mappings().all()
        return [
            {**dict(row), "metadata_json": _json_object(row.get("metadata_json"))}
            for row in rows
        ]

    def sleep_sessions(
        self,
        user_id: uuid.UUID,
        *,
        since: date | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT id, user_id, calendar_date, summary_json FROM sleep_sessions "
            "WHERE user_id = :user_id"
        )
        bound_user_id: Any = (
            user_id if self.db.get_bind().dialect.name == "postgresql" else str(user_id)
        )
        params: dict[str, Any] = {"user_id": bound_user_id}
        if since is not None:
            query += " AND calendar_date >= :since"
            params["since"] = since
        query += " ORDER BY calendar_date DESC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = max(int(limit), 1)
        rows = self.db.execute(text(query), params).mappings().all()
        return [
            {**dict(row), "summary_json": _json_object(row.get("summary_json"))}
            for row in rows
        ]


def get_training_store(db: Session = Depends(get_db)) -> CanonicalTrainingStore:
    """Construct the request-scoped canonical fitness repository."""
    return CanonicalTrainingStore(db)


def check_database_ready() -> tuple[bool, dict[str, str]]:
    """Check the canonical Postgres dependency used by product-facing routes."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pylint: disable=broad-except
        return False, {"postgres": f"error: {type(exc).__name__}"}
    return True, {"postgres": "ok"}
