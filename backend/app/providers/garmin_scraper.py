"""Wrapper around the community Garmin scraper to keep interfaces consistent."""

from __future__ import annotations

import logging
from typing import Any

from app.services.providers import decrypt_user_tokens
from app.models import UserProviderToken

GarminConnectClient: Any | None = None
try:
    from garth import Client as GarminConnectClient  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    GarminConnectClient = None

logger = logging.getLogger("providers.garmin_scraper")


class GarminScraperClient:
    """
    Thin wrapper to allow swapping the underlying Garmin integration later.
    For now, this is a placeholder for the unofficial Garmin Connect scraper.
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._client: Any | None = None

    def login(self):
        """Authenticate with Garmin Connect using stored credentials."""
        if GarminConnectClient is None:
            raise RuntimeError("garth client not installed; cannot use Garmin scraper")

        self._client = GarminConnectClient()
        self._client.login(self.username, self.password)
        return self._client

    def fetch_activities(self, limit: int = 10):
        """Fetch recent activities via the unofficial API."""
        if not self._client:
            self.login()
        client = self._client
        if client is None:
            raise RuntimeError("Garmin scraper client not initialized")
        return client.connectapi(
            f"activitylist-service/activities/search/activities?limit={limit}"
        )


def build_scraper_client(token: UserProviderToken) -> GarminScraperClient:
    """Create a scraper client from stored provider tokens."""
    creds = decrypt_user_tokens(token)
    username = creds["access_token"]
    password = creds["refresh_token"]
    if not username or not password:
        raise ValueError("Garmin scraper credentials missing username or password")
    return GarminScraperClient(username=username, password=password)
