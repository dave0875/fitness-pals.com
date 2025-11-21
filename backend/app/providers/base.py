"""Abstractions for third-party fitness providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class FitnessProvider(ABC):
    """
    Pluggable provider contract for fetching user data. Concrete implementations
    (Garmin, Strava, Apple Health via bridge, etc.) should implement the methods below.
    """

    name: str

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Return a new access token payload; may also return a new refresh token."""

    @abstractmethod
    def fetch_daily_stats(self, access_token: str, **kwargs) -> Dict[str, Any]:
        """Return normalized daily stats for the connected user."""

    @abstractmethod
    def fetch_activities(
        self,
        access_token: str,
        since: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Return normalized activity feed for the user."""
