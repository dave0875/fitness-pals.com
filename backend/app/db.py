"""SQLAlchemy session helpers and declarative Base for the backend."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

from .config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SESSION_FACTORY = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
)
Base = declarative_base()


def get_db():
    """Yield a database session scoped to the current request."""
    db = SESSION_FACTORY()
    try:
        yield db
    finally:
        db.close()
