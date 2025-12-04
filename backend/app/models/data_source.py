"""User-configured data source credentials."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PrimaryUUIDMixin, TimestampMixin, UserOwnedMixin


class DataSource(PrimaryUUIDMixin, UserOwnedMixin, TimestampMixin, Base):  # pylint: disable=too-few-public-methods
    """Encrypted Influx/Garmin sources registered per user."""

    __tablename__ = "data_sources"

    type: Mapped[str] = mapped_column(String, nullable=False, default="influxdb")
    influx_url: Mapped[str] = mapped_column(String, nullable=False)
    influx_org: Mapped[str] = mapped_column(String, nullable=False)
    influx_bucket: Mapped[str] = mapped_column(String, nullable=False)
    token_encrypted: Mapped[bytes] = mapped_column(BYTEA, nullable=False)

    user = relationship("User", backref="data_sources")
