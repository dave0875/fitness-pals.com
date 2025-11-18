from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Optional

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.utils.security import create_access_token, create_refresh_token

settings = get_settings()
oauth = OAuth()
logger = logging.getLogger("auth.oauth")
logger.setLevel(logging.INFO)


_registered = {}


def _register_provider(name: str, metadata_url: str, client_id: Optional[str], client_secret: Optional[str], scope: str):
    if not client_id or not client_secret:
        logger.info("Skipping OAuth registration; missing client config", extra={"provider": name})
        return
    oauth.register(
        name=name,
        server_metadata_url=metadata_url,
        client_id=client_id,
        client_secret=client_secret,
        client_kwargs={"scope": scope},
    )
    _registered[name] = True


_register_provider(
    "google",
    "https://accounts.google.com/.well-known/openid-configuration",
    settings.google_client_id,
    settings.google_client_secret,
    "openid email profile",
)
_register_provider(
    "microsoft",
    "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    settings.microsoft_client_id,
    settings.microsoft_client_secret,
    "openid email profile offline_access",
)
_register_provider(
    "apple",
    "https://appleid.apple.com/.well-known/openid-configuration",
    settings.apple_client_id,
    settings.apple_client_secret,
    "openid email name",
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _redirect_uri_for(provider: str) -> Optional[str]:
    mapping = {
        "google": str(settings.google_redirect_uri),
        "microsoft": str(settings.microsoft_redirect_uri) if settings.microsoft_redirect_uri else None,
        "apple": str(settings.apple_redirect_uri) if settings.apple_redirect_uri else None,
    }
    return mapping.get(provider)


async def _fetch_userinfo(provider: str, token, request: Request):
    client = getattr(oauth, provider)
    # Prefer userinfo endpoint if available
    try:
        if "userinfo_endpoint" in client.server_metadata:
            return await client.userinfo(token=token)
    except Exception:
        logger.warning("Failed to fetch userinfo via endpoint", extra={"provider": provider})
    # Fallback to ID token claims
    try:
        claims = await client.parse_id_token(request, token)
        if claims:
            return claims
    except Exception:
        logger.info("ID token parse failed", extra={"provider": provider})
    return token.get("userinfo")


def _require_provider(provider: str):
    if provider not in _registered:
        raise HTTPException(status_code=404, detail=f"Provider {provider} not configured")


@router.get("/{provider}/login")
async def login(provider: str, request: Request):
    provider = provider.lower()
    _require_provider(provider)
    redirect_uri = _redirect_uri_for(provider)
    if not redirect_uri:
        raise HTTPException(status_code=500, detail=f"Missing redirect URI for {provider}")
    client = getattr(oauth, provider)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/login")
async def login_google(request: Request):
    """Backward-compatible Google login endpoint."""
    return await login("google", request)


@router.get("/{provider}/callback")
async def auth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    provider = provider.lower()
    _require_provider(provider)
    client = getattr(oauth, provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    userinfo = await _fetch_userinfo(provider, token, request)
    if not userinfo:
        raise HTTPException(status_code=400, detail=f"No userinfo from {provider}")
    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail=f"{provider} did not return an email")
    user: Optional[User] = db.query(User).filter(User.email == email).first()
    now = datetime.utcnow()
    if not user:
        user = User(email=email, name=userinfo.get("name"), picture_url=userinfo.get("picture"), created_at=now, last_login_at=now)
        db.add(user)
    else:
        user.last_login_at = now
    db.commit()
    db.refresh(user)
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@router.get("/callback")
async def auth_callback_google(request: Request, db: Session = Depends(get_db)):
    """Backward-compatible Google callback endpoint."""
    return await auth_callback("google", request, db)
