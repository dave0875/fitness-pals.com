from __future__ import annotations

import logging
from typing import Optional

from app.services.providers import decrypt_user_tokens
from app.models import UserProviderToken

logger = logging.getLogger("providers.garmin_scraper")


class GarminScraperClient:
    """
    Thin wrapper to allow swapping the underlying Garmin integration later.
    For now, this is a placeholder for the unofficial Garmin Connect scraper.
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._client = None

    def login(self):
        try:
            # Lazy import so environments without the scraper library still run tests.
            from garth import Client  # type: ignore
        except Exception as err:  # pragma: no cover - optional dependency
            raise RuntimeError("garth client not installed; cannot use Garmin scraper") from err

        self._client = Client()
        self._client.login(self.username, self.password)
        return self._client

    def fetch_activities(self, limit: int = 10):
        if not self._client:
            self.login()
        return self._client.connectapi(f"activitylist-service/activities/search/activities?limit={limit}")


def build_scraper_client(token: UserProviderToken) -> GarminScraperClient:
    creds = decrypt_user_tokens(token)
    username = creds["access_token"]
    password = creds["refresh_token"]
    if not username or not password:
        raise ValueError("Garmin scraper credentials missing username or password")
    return GarminScraperClient(username=username, password=password)
