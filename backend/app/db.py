"""SQLAlchemy session helpers and declarative Base for the backend."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

from .config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SESSION_FACTORY = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
)


class Base(DeclarativeBase):
    """Declarative base for ORM models with basic helpers."""

    def as_dict(self) -> dict:
        """Return a dict of column keys to values."""
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={getattr(self, 'id', None)}>"


def get_db():
    """Yield a database session scoped to the current request."""
    db = SESSION_FACTORY()
    try:
        yield db
    finally:
        db.close()
