"""OAuth provider metadata and per-user token storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.dialects.postgresql import UUID, BYTEA
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class ProviderApp(PrimaryUUIDMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """
    Represents a provider OAuth app/client that the platform owns (e.g., Garmin, Strava).
    Stores client credentials encrypted so environments can be configured through the API
    instead of baking them into .env for all users.
    """

    __tablename__ = "provider_apps"

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    client_id: Mapped[str] = mapped_column(String, nullable=False)
    client_secret_encrypted: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    auth_url: Mapped[str | None] = mapped_column(String, nullable=True)
    token_url: Mapped[str | None] = mapped_column(String, nullable=True)
    scopes: Mapped[str | None] = mapped_column(String, nullable=True)


class UserProviderToken(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """
    User-specific grant for a provider. Access/refresh tokens are encrypted, and a small
    amount of metadata (scopes, provider user id) is stored for orchestration.
    """

    __tablename__ = "user_provider_tokens"

    tenant_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token_encrypted: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    user = relationship("User", backref="provider_tokens")
