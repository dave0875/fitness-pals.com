"""Typed configuration helpers for the backend service."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Optional

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic model representing all runtime configuration values."""

    # --- Core app settings ---
    app_name: str = "Run Trainer"
    debug: bool = False

    # --- JWT / Auth ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_exp_minutes: int = 30
    refresh_token_exp_days: int = 30

    # --- OAuth: Google ---
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: AnyUrl

    # --- OAuth: Optional Microsoft / Apple ---
    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None
    microsoft_redirect_uri: Optional[AnyUrl] = None

    apple_client_id: Optional[str] = None
    apple_client_secret: Optional[str] = None
    apple_redirect_uri: Optional[AnyUrl] = None

    # --- Database ---
    database_url: str

    # --- Influx + OpenAI ---
    influx_default_url: Optional[str] = None
    openai_api_key: Optional[str] = None

    # --- Token encryption ---
    fernet_key: str

    # --- Ingestion / dedupe tolerances ---
    dedupe_start_time_tolerance_seconds: int = 90
    dedupe_duration_tolerance_ratio: float = 0.1
    dedupe_distance_tolerance_ratio: float = 0.03

    # ---------- NEW Pydantic v2 config -----------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RUNTRAINER_",
        extra="ignore",  # Helps avoid failing on irrelevant test env vars
    )


@lru_cache
def get_settings() -> Settings:
    """
    Runtime settings loader.
    Uses .env.test automatically during pytest runs.
    """
    if "pytest" in sys.modules:
        return Settings(_env_file=".env.test")  # type: ignore[call-arg]

    return Settings()  # type: ignore[call-arg]


# Frontend flavor: "legacy" (default) or "wellness"
FRONTEND_FLAVOR = (os.environ.get("FRONTEND_FLAVOR") or "legacy").lower()


def is_wellness_ui_enabled() -> bool:
    """Return True when the wellness UI should be served."""
    return FRONTEND_FLAVOR == "wellness"
