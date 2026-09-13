"""Issue, atomically rotate, revoke, and clean up app refresh sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshTokenSession
from app.utils.security import (
    InvalidAppToken,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)

settings = get_settings()


class RefreshTokenRejected(ValueError):
    """Raised uniformly for invalid, unknown, consumed, or revoked refresh state."""


@dataclass(frozen=True)
class TokenPair:
    """New app credentials and the durable identifier for the refresh half."""

    access_token: str
    refresh_token: str
    refresh_jti: uuid.UUID


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current


def cleanup_expired_refresh_sessions(db: Session, *, now: datetime | None = None) -> None:
    """Bound persistent state by removing credentials that can no longer validate."""
    current = _now(now)
    db.execute(
        delete(RefreshTokenSession).where(RefreshTokenSession.expires_at <= current)
    )


def issue_token_pair(
    db: Session,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> TokenPair:
    """Stage a fresh token pair and matching refresh state in the caller's transaction."""
    current = _now(now)
    refresh_jti = uuid.uuid4()
    cleanup_expired_refresh_sessions(db, now=current)
    db.add(
        RefreshTokenSession(
            jti=refresh_jti,
            user_id=user_id,
            issued_at=current,
            expires_at=current + timedelta(days=settings.refresh_token_exp_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(user_id, issued_at=current),
        refresh_token=create_refresh_token(
            user_id,
            jti=refresh_jti,
            issued_at=current,
        ),
        refresh_jti=refresh_jti,
    )


def _refresh_identity(raw_token: str) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        claims = decode_refresh_token(raw_token)
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["jti"])
    except (InvalidAppToken, KeyError, TypeError, ValueError) as exc:
        raise RefreshTokenRejected("invalid refresh token") from exc


def rotate_refresh_token(
    db: Session,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> TokenPair:
    """Consume one refresh session exactly once and atomically persist its successor."""
    user_id, refresh_jti = _refresh_identity(raw_token)
    current = _now(now)
    try:
        result = db.execute(
            update(RefreshTokenSession)
            .where(
                RefreshTokenSession.jti == refresh_jti,
                RefreshTokenSession.user_id == user_id,
                RefreshTokenSession.consumed_at.is_(None),
                RefreshTokenSession.revoked_at.is_(None),
                RefreshTokenSession.expires_at > current,
            )
            .values(consumed_at=current)
        )
        if getattr(result, "rowcount", 0) != 1:
            db.rollback()
            raise RefreshTokenRejected("invalid refresh token")
        replacement = issue_token_pair(db, user_id, now=current)
        db.commit()
        return replacement
    except RefreshTokenRejected:
        raise
    except Exception:
        db.rollback()
        raise


def revoke_refresh_token(
    db: Session,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Durably revoke the active refresh session represented by a strict refresh JWT."""
    user_id, refresh_jti = _refresh_identity(raw_token)
    current = _now(now)
    try:
        result = db.execute(
            update(RefreshTokenSession)
            .where(
                RefreshTokenSession.jti == refresh_jti,
                RefreshTokenSession.user_id == user_id,
                RefreshTokenSession.consumed_at.is_(None),
                RefreshTokenSession.revoked_at.is_(None),
                RefreshTokenSession.expires_at > current,
            )
            .values(revoked_at=current)
        )
        if getattr(result, "rowcount", 0) != 1:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
