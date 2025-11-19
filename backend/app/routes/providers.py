from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.deps import get_current_user
from app.db import get_db
from app.models import ProviderApp, User, UserProviderToken
from app.services.providers import get_provider_app, list_provider_apps, save_user_provider_token, upsert_provider_app


class ProviderAppRequest(BaseModel):
    provider: str = Field(..., description="Provider key such as garmin, strava, apple_health")
    client_id: str
    client_secret: Optional[str] = None
    display_name: Optional[str] = None
    auth_url: Optional[HttpUrl] = None
    token_url: Optional[HttpUrl] = None
    scopes: Optional[str] = Field(None, description="Space- or comma-separated scopes")


class ProviderTokenRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    provider_user_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Optional[dict] = Field(default=None, description="Arbitrary provider-specific metadata")


class GarminScraperConnectRequest(BaseModel):
    """Credentials for the unofficial Garmin Connect scraper (per user)."""

    username: str
    password: str


router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/apps")
def list_apps(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # TODO: gate this to admins/ops users. For now we allow authenticated users to view apps.
    apps = list_provider_apps(db)
    return [
        {
            "id": str(app.id),
            "provider": app.provider,
            "display_name": app.display_name,
            "client_id": app.client_id,
            "auth_url": app.auth_url,
            "token_url": app.token_url,
            "scopes": app.scopes,
            "has_client_secret": bool(app.client_secret_encrypted),
            "created_at": app.created_at,
            "updated_at": app.updated_at,
        }
        for app in apps
    ]


@router.post("/apps")
def create_or_update_app(body: ProviderAppRequest, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # This lets ops register Garmin/Strava/etc. app credentials without baking them into .env.
    app = upsert_provider_app(
        db,
        provider=body.provider.lower(),
        client_id=body.client_id,
        client_secret=body.client_secret,
        display_name=body.display_name,
        auth_url=str(body.auth_url) if body.auth_url else None,
        token_url=str(body.token_url) if body.token_url else None,
        scopes=body.scopes,
    )
    return {"id": str(app.id), "provider": app.provider, "display_name": app.display_name}


@router.post("/{provider}/connect")
def connect_provider(
    provider: str,
    body: ProviderTokenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider_key = provider.lower()
    app: Optional[ProviderApp] = get_provider_app(db, provider_key)
    if not app:
        raise HTTPException(status_code=404, detail=f"No provider app configured for {provider_key}")
    token: UserProviderToken = save_user_provider_token(
        db,
        user_id=user.id,
        provider=provider_key,
        access_token=body.access_token,
        refresh_token=body.refresh_token,
        scope=body.scope,
        provider_user_id=body.provider_user_id,
        expires_at=body.expires_at,
        metadata=body.metadata,
    )
    return {"status": "ok", "provider": token.provider, "user_id": str(token.user_id)}


@router.post("/garmin/scraper/connect")
def connect_garmin_scraper(
    body: GarminScraperConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Store per-user Garmin credentials for the unofficial scraper flow.
    Note: this is intended as a bridge until Garmin Health API onboarding is available.
    Username is stored in access_token_encrypted, password in refresh_token_encrypted.
    """
    token: UserProviderToken = save_user_provider_token(
        db,
        user_id=user.id,
        provider="garmin_scraper",
        access_token=body.username,
        refresh_token=body.password,
        scope=None,
        provider_user_id=None,
        metadata={"mode": "scraper", "created_at": datetime.utcnow().isoformat()},
    )
    return {"status": "ok", "provider": token.provider, "user_id": str(token.user_id)}


@router.get("/me")
def list_user_connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tokens = db.query(UserProviderToken).filter(UserProviderToken.user_id == user.id).all()
    return [
        {
            "provider": t.provider,
            "provider_user_id": t.provider_user_id,
            "scope": t.scope,
            "expires_at": t.expires_at,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "metadata": t.metadata,
        }
        for t in tokens
    ]


@router.get("/{provider}/app")
def get_app(provider: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = get_provider_app(db, provider.lower())
    if not app:
        raise HTTPException(status_code=404, detail=f"No provider app configured for {provider}")
    return {
        "id": str(app.id),
        "provider": app.provider,
        "display_name": app.display_name,
        "client_id": app.client_id,
        "auth_url": app.auth_url,
        "token_url": app.token_url,
        "scopes": app.scopes,
        "has_client_secret": bool(app.client_secret_encrypted),
        # Secret is not exposed here to avoid accidental leakage.
    }
