from __future__ import annotations

from typing import Any, Dict, Optional

from .base import FitnessProvider


class GarminProvider(FitnessProvider):
    """
    Placeholder adapter for Garmin. The real implementation should:
    - Use the per-user tokens stored in user_provider_tokens
    - Refresh tokens via the Garmin token endpoint
    - Normalize activity/sleep metrics into the schema the ingestion pipeline expects
    """

    name = "garmin"

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        raise NotImplementedError("Garmin token refresh not yet implemented")

    def fetch_daily_stats(self, access_token: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("Garmin adapter not yet implemented")

    def fetch_activities(self, access_token: str, since: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("Garmin adapter not yet implemented")
