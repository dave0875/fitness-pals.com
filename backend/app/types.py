"""Shared structural protocol definitions used across the backend."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class CurrentUserLike(Protocol):
    """Minimal user shape accessed by routes and services."""

    @property
    def id(self) -> UUID:
        ...

    @property
    def tenant_id(self) -> UUID | None:
        ...


class InfluxQueryApiLike(Protocol):
    """Subset of the Influx query API used in the codebase."""

    def query(self, *, org: str, query: str) -> Any:
        ...

    def query_raw(self, *, org: str, query: str) -> Any:
        ...


class InfluxWriteApiLike(Protocol):
    """Subset of the Influx write API."""

    def write(self, *, bucket: str, org: str, record: Any) -> Any:
        ...

    def close(self) -> Any:
        ...


class InfluxDeleteApiLike(Protocol):
    """Subset of the Influx delete API."""

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def close(self) -> Any:
        ...


class InfluxClientLike(Protocol):
    """Influx client attributes/methods relied upon by services and routes."""

    org: str
    default_bucket: str

    def query_api(self) -> InfluxQueryApiLike:
        ...

    def write_api(self) -> InfluxWriteApiLike:
        ...

    def delete_api(self) -> InfluxDeleteApiLike:
        ...
