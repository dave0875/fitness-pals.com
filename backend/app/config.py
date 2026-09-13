"""Typed configuration helpers for the backend service."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Any, Optional

from pydantic import AnyUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic model representing all runtime configuration values."""

    # --- Core app settings ---
    app_name: str = "Run Trainer"
    debug: bool = False

    # --- JWT / Auth ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "https://fitness-pals.com"
    jwt_access_audience: str = "fitness-pals-api"
    jwt_refresh_audience: str = "fitness-pals-refresh"
    access_token_exp_minutes: int = 30
    refresh_token_exp_days: int = 30

    @field_validator(
        "jwt_issuer",
        "jwt_access_audience",
        "jwt_refresh_audience",
    )
    @classmethod
    def nonempty_app_jwt_boundary(cls, value: str) -> str:
        """Reject boundary values that would make app-token identity ambiguous."""
        if not value.strip():
            raise ValueError("app JWT boundary values cannot be empty")
        return value

    @model_validator(mode="after")
    def distinct_app_jwt_audiences(self) -> "Settings":
        """Access and refresh credentials must never share an audience."""
        if self.jwt_access_audience == self.jwt_refresh_audience:
            raise ValueError("app JWT access and refresh audiences must be distinct")
        return self

    # --- OAuth: Google fallback ---
    google_fallback_enabled: bool = False
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[AnyUrl] = None

    # --- OAuth: Authentik / OIDC broker ---
    oidc_issuer: Optional[AnyUrl] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_redirect_uri: Optional[AnyUrl] = None
    oidc_scope: str = "openid email profile"
    web_oidc_issuer: Optional[AnyUrl] = None
    web_oidc_client_id: Optional[str] = None
    web_oidc_client_secret: Optional[str] = None
    web_oidc_redirect_uri: Optional[AnyUrl] = None
    web_oidc_scope: Optional[str] = None

    # --- OAuth: Optional Microsoft / Apple ---
    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None
    microsoft_redirect_uri: Optional[AnyUrl] = None

    apple_client_id: Optional[str] = None
    apple_client_secret: Optional[str] = None
    apple_redirect_uri: Optional[AnyUrl] = None

    @field_validator(
        "google_redirect_uri",
        "oidc_issuer",
        "oidc_redirect_uri",
        "web_oidc_issuer",
        "web_oidc_redirect_uri",
        "microsoft_redirect_uri",
        "apple_redirect_uri",
        mode="before",
    )
    @classmethod
    def empty_optional_url_as_none(cls, value: Any) -> Any:
        """Treat empty Compose-provided optional URLs as unconfigured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

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

    # --- Athlete-bound archive ingestion ---
    archive_import_storage_backend: str = "filesystem"
    archive_import_filesystem_root: str = "/tmp/runtrainer-archive-imports"
    archive_import_upload_url_ttl_seconds: int = 3600
    archive_import_gcs_bucket: Optional[str] = None
    archive_import_gcs_credentials_json: Optional[str] = None
    archive_import_gcs_credentials_file: Optional[str] = None
    google_drive_archive_sources_json: str = "{}"
    google_drive_service_account_json: Optional[str] = None
    google_drive_service_account_file: Optional[str] = None
    google_drive_archive_max_objects: int = 10000

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
    if "pytest" in sys.modules and os.path.exists(".env.test"):
        return Settings(_env_file=".env.test")  # type: ignore[call-arg]

    return Settings()  # type: ignore[call-arg]


# Frontend flavor: "legacy" (default) or "wellness"
FRONTEND_FLAVOR = (os.environ.get("FRONTEND_FLAVOR") or "legacy").lower()


def is_wellness_ui_enabled() -> bool:
    """Return True when the wellness UI should be served."""
    return FRONTEND_FLAVOR == "wellness"
