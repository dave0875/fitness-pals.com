from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID, BYTEA
from sqlalchemy.orm import relationship

from app.db import Base


class ProviderApp(Base):
    """
    Represents a provider OAuth app/client that the platform owns (e.g., Garmin, Strava).
    Stores client credentials encrypted so environments can be configured through the API
    instead of baking them into .env for all users.
    """

    __tablename__ = "provider_apps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    client_id = Column(String, nullable=False)
    client_secret_encrypted = Column(BYTEA, nullable=True)
    auth_url = Column(String, nullable=True)
    token_url = Column(String, nullable=True)
    scopes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserProviderToken(Base):
    """
    User-specific grant for a provider. Access/refresh tokens are encrypted, and a small
    amount of metadata (scopes, provider user id) is stored for orchestration.
    """

    __tablename__ = "user_provider_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    provider_user_id = Column(String, nullable=True)
    access_token_encrypted = Column(BYTEA, nullable=False)
    refresh_token_encrypted = Column(BYTEA, nullable=True)
    scope = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", backref="provider_tokens")
