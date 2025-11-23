"""CRUD helpers for provider applications and encrypted user tokens."""

# pylint: disable=duplicate-code

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ProviderApp, UserProviderToken
from app.utils.security import decrypt_token, encrypt_token


logger = logging.getLogger("providers")


@dataclass
class ProviderAppDetails:  # pylint: disable=too-many-instance-attributes
    """Incoming data for creating/updating a provider app."""

    provider: str
    client_id: str
    client_secret: Optional[str] = None
    display_name: Optional[str] = None
    auth_url: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Optional[str] = None


@dataclass
class ProviderTokenDetails:  # pylint: disable=too-many-instance-attributes
    """Encrypted token payload stored per user."""

    user_id: UUID
    provider: str
    access_token: str
    tenant_id: Optional[UUID] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    provider_user_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Optional[dict] = None


def get_provider_app(db: Session, provider: str) -> Optional[ProviderApp]:
    """Fetch a provider app by key."""
    return db.query(ProviderApp).filter(ProviderApp.provider == provider).first()


def upsert_provider_app(db: Session, details: ProviderAppDetails) -> ProviderApp:
    """Insert or update a provider app row."""
    existing = get_provider_app(db, details.provider)
    secret_encrypted = (
        encrypt_token(details.client_secret) if details.client_secret else None
    )
    if existing:
        existing.client_id = details.client_id
        existing.display_name = details.display_name
        existing.auth_url = details.auth_url
        existing.token_url = details.token_url
        existing.scopes = details.scopes
        if details.client_secret:
            existing.client_secret_encrypted = secret_encrypted
        db.commit()
        db.refresh(existing)
        return existing

    app = ProviderApp(
        provider=details.provider,
        client_id=details.client_id,
        client_secret_encrypted=secret_encrypted,
        display_name=details.display_name,
        auth_url=details.auth_url,
        token_url=details.token_url,
        scopes=details.scopes,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


def list_provider_apps(db: Session) -> list[ProviderApp]:
    """Return all configured provider apps."""
    return db.query(ProviderApp).order_by(ProviderApp.provider.asc()).all()


def get_user_provider_token(
    db: Session, user_id: UUID, provider: str, tenant_id: Optional[UUID] = None
) -> Optional[UserProviderToken]:
    """Fetch a user's token for a provider."""
    return (
        db.query(UserProviderToken)
        .filter(
            UserProviderToken.user_id == user_id,
            UserProviderToken.tenant_id == tenant_id,
            UserProviderToken.provider == provider,
        )
        .first()
    )


def save_user_provider_token(
    db: Session, details: ProviderTokenDetails
) -> UserProviderToken:
    """Insert or update a user's encrypted provider token."""
    if not details.access_token:
        raise ValueError("access_token is required to store provider token")
    logger.info(
        "saving provider token",
        extra={
            "user_id": str(details.user_id),
            "tenant_id": str(details.tenant_id) if details.tenant_id else None,
            "provider": details.provider,
            "expires_at": details.expires_at.isoformat() if details.expires_at else None,
            "has_refresh": bool(details.refresh_token),
            "metadata_keys": list(details.metadata.keys()) if details.metadata else [],
        },
    )
    existing = get_user_provider_token(
        db, details.user_id, details.provider, details.tenant_id
    )
    encrypted_access = encrypt_token(details.access_token)
    encrypted_refresh = (
        encrypt_token(details.refresh_token) if details.refresh_token else None
    )
    if existing:
        existing.access_token_encrypted = encrypted_access
        existing.refresh_token_encrypted = encrypted_refresh
        existing.scope = details.scope
        existing.provider_user_id = details.provider_user_id
        existing.expires_at = details.expires_at
        existing.metadata_json = details.metadata
        existing.tenant_id = details.tenant_id
        db.commit()
        db.refresh(existing)
        logger.info(
            "provider token updated",
            extra={
                "user_id": str(details.user_id),
                "tenant_id": str(details.tenant_id) if details.tenant_id else None,
                "provider": details.provider,
                "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
                "has_refresh": bool(details.refresh_token),
            },
        )
        return existing

    token = UserProviderToken(
        user_id=details.user_id,
        tenant_id=details.tenant_id,
        provider=details.provider,
        access_token_encrypted=encrypted_access,
        refresh_token_encrypted=encrypted_refresh,
        scope=details.scope,
        provider_user_id=details.provider_user_id,
        expires_at=details.expires_at,
        metadata_json=details.metadata,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info(
        "provider token created",
        extra={
            "user_id": str(details.user_id),
            "tenant_id": str(details.tenant_id) if details.tenant_id else None,
            "provider": details.provider,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "has_refresh": bool(details.refresh_token),
        },
    )
    return token


def decrypt_provider_app_secret(app: ProviderApp) -> Optional[str]:
    """Return the decrypted provider secret or None."""
    if not app.client_secret_encrypted:
        return None
    return decrypt_token(app.client_secret_encrypted)


def decrypt_user_tokens(token: UserProviderToken) -> dict:
    """Decrypt stored per-user provider credentials."""
    return {
        "access_token": decrypt_token(token.access_token_encrypted),
        "refresh_token": (
            decrypt_token(token.refresh_token_encrypted)
            if token.refresh_token_encrypted
            else None
        ),
        "scope": token.scope,
        "provider_user_id": token.provider_user_id,
        "expires_at": token.expires_at,
        "metadata": token.metadata_json or {},
    }
