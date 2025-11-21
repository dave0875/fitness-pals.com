"""Typed configuration helpers for the backend service."""

from __future__ import annotations

import sys

from functools import lru_cache
from typing import Optional

from pydantic import AnyUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Pydantic model representing all runtime configuration values."""

    app_name: str = "Run Trainer"
    debug: bool = False
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_exp_minutes: int = 30
    refresh_token_exp_days: int = 30

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: AnyUrl

    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None
    microsoft_redirect_uri: Optional[AnyUrl] = None

    apple_client_id: Optional[str] = None
    apple_client_secret: Optional[str] = None
    apple_redirect_uri: Optional[AnyUrl] = None

    database_url: str

    influx_default_url: Optional[str] = None
    openai_api_key: Optional[str] = None

    fernet_key: str

    dedupe_start_time_tolerance_seconds: int = 90
    dedupe_duration_tolerance_ratio: float = 0.1
    dedupe_distance_tolerance_ratio: float = 0.03

    class Config:  # pylint: disable=too-few-public-methods
        """Pydantic-specific configuration metadata."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "RUNTRAINER_"


@lru_cache


def get_settings():
    """Return settings for test scenarios."""
    if "pytest" in sys.modules:
        return Settings(_env_file=".env.test")
    return Settings()
