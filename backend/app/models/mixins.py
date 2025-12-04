"""Reusable column mixins to avoid duplication across models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class PrimaryUUIDMixin:  # pylint: disable=too-few-public-methods
    """Provides a UUID primary key."""

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class UserOwnedMixin:  # pylint: disable=too-few-public-methods
    """Provides a user_id foreign key."""

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class TimestampMixin:  # pylint: disable=too-few-public-methods
    """Provides created_at/updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
