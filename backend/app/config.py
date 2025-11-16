from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseSettings, AnyUrl


class Settings(BaseSettings):
    app_name: str = "Run Trainer"
    debug: bool = False
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_exp_minutes: int = 30
    refresh_token_exp_days: int = 30

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: AnyUrl

    database_url: str

    influx_default_url: Optional[str] = None
    openai_api_key: Optional[str] = None

    fernet_key: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
