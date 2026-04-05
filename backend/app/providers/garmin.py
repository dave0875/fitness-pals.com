"""Garmin provider adapter backed by the existing Garmin ingest bridge."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services import garmin_ingest

from .base import FitnessProvider


class GarminBridgeClient:
    """Bridge seam that preserves the current Garmin ingest path."""

    def fetch_daily_stats(self, access_token: str, **kwargs) -> Dict[str, Any]:
        """Run the existing Garmin ingest flow and return its summary."""
        del access_token
        ingest_run = self.fetch_activities("", **kwargs)
        summary = getattr(ingest_run, "summary", None)
        return summary if isinstance(summary, dict) else {}

    def fetch_activities(
        self,
        access_token: str,
        since: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Delegate activity sync to the current Garmin ingest helper."""
        del access_token, since
        db = kwargs["db"]
        user = kwargs["user"]
        test_run = kwargs.get("test_run", False)
        return garmin_ingest.fetch_garmin_recent(db, user, test_run=test_run)


class GarminProvider(FitnessProvider):
    """
    Provider adapter that currently bridges into the existing Garmin ingest flow.
    This keeps orchestration on a provider seam without changing the ingest path.
    """

    name = "garmin"
    bridge_client = GarminBridgeClient()

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange a refresh token for a new access token."""
        raise NotImplementedError("Garmin token refresh not yet implemented")

    def fetch_daily_stats(self, access_token: str, **kwargs) -> Dict[str, Any]:
        """Return daily stats through the bridge seam."""
        return self.bridge_client.fetch_daily_stats(access_token, **kwargs)

    def fetch_activities(
        self,
        access_token: str,
        since: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Return activities through the bridge seam."""
        return self.bridge_client.fetch_activities(access_token, since=since, **kwargs)
