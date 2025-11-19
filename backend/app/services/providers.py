from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ProviderApp, UserProviderToken
from app.utils.security import encrypt_token, decrypt_token


def get_provider_app(db: Session, provider: str) -> Optional[ProviderApp]:
    return db.query(ProviderApp).filter(ProviderApp.provider == provider).first()


def upsert_provider_app(
    db: Session,
    *,
    provider: str,
    client_id: str,
    client_secret: Optional[str] = None,
    display_name: Optional[str] = None,
    auth_url: Optional[str] = None,
    token_url: Optional[str] = None,
    scopes: Optional[str] = None,
) -> ProviderApp:
    existing = get_provider_app(db, provider)
    secret_encrypted = encrypt_token(client_secret) if client_secret else None
    if existing:
        existing.client_id = client_id
        existing.display_name = display_name
        existing.auth_url = auth_url
        existing.token_url = token_url
        existing.scopes = scopes
        if client_secret:
            existing.client_secret_encrypted = secret_encrypted
        db.commit()
        db.refresh(existing)
        return existing

    app = ProviderApp(
        provider=provider,
        client_id=client_id,
        client_secret_encrypted=secret_encrypted,
        display_name=display_name,
        auth_url=auth_url,
        token_url=token_url,
        scopes=scopes,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


def list_provider_apps(db: Session) -> list[ProviderApp]:
    return db.query(ProviderApp).order_by(ProviderApp.provider.asc()).all()


def get_user_provider_token(db: Session, user_id, provider: str) -> Optional[UserProviderToken]:
    return (
        db.query(UserProviderToken)
        .filter(UserProviderToken.user_id == user_id, UserProviderToken.provider == provider)
        .first()
    )


def save_user_provider_token(
    db: Session,
    *,
    user_id,
    provider: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    scope: Optional[str] = None,
    provider_user_id: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> UserProviderToken:
    if not access_token:
        raise ValueError("access_token is required to store provider token")
    existing = get_user_provider_token(db, user_id, provider)
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None
    if existing:
        existing.access_token_encrypted = encrypted_access
        existing.refresh_token_encrypted = encrypted_refresh
        existing.scope = scope
        existing.provider_user_id = provider_user_id
        existing.expires_at = expires_at
        existing.metadata = metadata
        db.commit()
        db.refresh(existing)
        return existing

    token = UserProviderToken(
        user_id=user_id,
        provider=provider,
        access_token_encrypted=encrypted_access,
        refresh_token_encrypted=encrypted_refresh,
        scope=scope,
        provider_user_id=provider_user_id,
        expires_at=expires_at,
        metadata=metadata,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def decrypt_provider_app_secret(app: ProviderApp) -> Optional[str]:
    if not app.client_secret_encrypted:
        return None
    return decrypt_token(app.client_secret_encrypted)


def decrypt_user_tokens(token: UserProviderToken) -> dict:
    return {
        "access_token": decrypt_token(token.access_token_encrypted),
        "refresh_token": decrypt_token(token.refresh_token_encrypted) if token.refresh_token_encrypted else None,
        "scope": token.scope,
        "provider_user_id": token.provider_user_id,
        "expires_at": token.expires_at,
        "metadata": token.metadata or {},
    }
