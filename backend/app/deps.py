"""Dependency helpers shared across backend routes."""

from __future__ import annotations

import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.config import get_settings
from app.db import get_db
from app.models import User

settings = get_settings()
bearer = HTTPBearer(auto_error=False)


def _resolve_google_user(token: str, db: Session) -> User:
    """Verify a Google token and return or create a user."""
    request_obj = google_requests.Request()
    claims = google_id_token.verify_oauth2_token(token, request_obj, settings.google_client_id)
    email = claims.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            name=claims.get("name"),
            picture_url=claims.get("picture"),
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except Exception as commit_exc:  # pylint: disable=broad-except
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user",
            ) from commit_exc
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    """Resolve the current authenticated user from the Authorization header."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credentials missing")
    token = credentials.credentials
    # First try app-issued JWT
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("sub missing")
        uid = uuid.UUID(user_id)
    except (JWTError, ValueError) as exc:
        try:
            return _resolve_google_user(token, db)
        except HTTPException as auth_exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=auth_exc.detail,
            ) from exc
        except Exception as fallback_exc:  # pragma: no cover
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from fallback_exc
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
