from __future__ import annotations

import uuid
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
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="No userinfo from Google")
    email = userinfo["email"]
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
