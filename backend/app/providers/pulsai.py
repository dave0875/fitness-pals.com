"""PulsAI MCP provider adapter for Garmin-backed fitness data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.models import Activity, ActivitySource, IngestRun
from app.services.providers import decrypt_user_tokens, get_user_provider_token

from .base import FitnessProvider


class PulsaiMcpError(RuntimeError):
    """A sanitized remote MCP transport or protocol failure."""


class PulsaiMcpClient:
    """Minimal MCP Streamable HTTP client for a private PulsAI endpoint."""

    protocol_version = "2025-03-26"

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 202 or not response.content:
            return {}
        content_type = response.headers.get("content-type", "")
        try:
            if "text/event-stream" in content_type:
                for line in response.text.splitlines():
                    if line.startswith("data:"):
                        return json.loads(line[5:].strip())
                raise ValueError("missing SSE data event")
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise PulsaiMcpError("PulsAI MCP returned an invalid response") from exc

    def _post(
        self,
        client: httpx.Client,
        endpoint: str,
        payload: dict[str, Any],
        *,
        session_id: Optional[str] = None,
    ) -> tuple[dict[str, Any], Optional[str]]:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        if session_id:
            headers["mcp-session-id"] = session_id
        try:
            response = client.post(endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise PulsaiMcpError("PulsAI MCP request failed") from exc
        if response.status_code >= 400:
            raise PulsaiMcpError(
                f"PulsAI MCP request failed with HTTP {response.status_code}"
            )
        return self._decode_response(response), response.headers.get("mcp-session-id")

    def call_tool(
        self, endpoint: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Initialize an MCP session and invoke one read-only PulsAI tool."""
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            initialized, session_id = self._post(
                client,
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": self.protocol_version,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "fitness-pals",
                            "version": "1.0",
                        },
                    },
                },
            )
            if initialized.get("error"):
                code = initialized["error"].get("code", "unknown")
                raise PulsaiMcpError(f"PulsAI MCP initialization failed ({code})")
            self._post(
                client,
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                session_id=session_id,
            )
            result, _ = self._post(
                client,
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                session_id=session_id,
            )
        if result.get("error"):
            code = result["error"].get("code", "unknown")
            raise PulsaiMcpError(f"PulsAI MCP tool call failed ({code})")
        tool_result = result.get("result") or {}
        structured = tool_result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for item in tool_result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    parsed = json.loads(item.get("text") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {}


def _activity_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        payload.get("activities"),
        (payload.get("data") or {}).get("activities")
        if isinstance(payload.get("data"), dict)
        else None,
        payload.get("items"),
    ):
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return value if isinstance(value, datetime) else None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(item: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if item.get(key) is not None:
            try:
                return float(item[key])
            except (TypeError, ValueError):
                return None
    return None


def _provider_activity_id(item: dict[str, Any]) -> Optional[str]:
    value = item.get("activity_id") or item.get("activityId") or item.get("id")
    return str(value) if value not in (None, "") else None


def _find_activity(db: Any, user_id: Any, fingerprint: str) -> Optional[Activity]:
    try:
        return (
            db.query(Activity)
            .filter(
                Activity.user_id == user_id,
                Activity.fingerprint_hash == fingerprint,
            )
            .first()
        )
    except Exception:  # pragma: no cover - lightweight test session fallback
        return next(
            (
                row
                for row in getattr(db, "items", [])
                if isinstance(row, Activity)
                and row.user_id == user_id
                and row.fingerprint_hash == fingerprint
            ),
            None,
        )


def _find_source(
    db: Any, activity_id: Any, provider_activity_id: str
) -> Optional[ActivitySource]:
    try:
        return (
            db.query(ActivitySource)
            .filter(
                ActivitySource.activity_id == activity_id,
                ActivitySource.provider == "pulsai",
                ActivitySource.provider_activity_id == provider_activity_id,
            )
            .first()
        )
    except Exception:  # pragma: no cover - lightweight test session fallback
        return next(
            (
                row
                for row in getattr(db, "items", [])
                if isinstance(row, ActivitySource)
                and row.activity_id == activity_id
                and row.provider == "pulsai"
                and row.provider_activity_id == provider_activity_id
            ),
            None,
        )


def _persist_activities(
    db: Any,
    user: Any,
    run: IngestRun,
    items: list[dict[str, Any]],
    *,
    test_run: bool,
) -> tuple[int, int]:
    created = 0
    linked = 0
    now = datetime.now(timezone.utc)
    for item in items:
        source_id = _provider_activity_id(item)
        if not source_id:
            continue
        start_time = _parse_datetime(
            item.get("start_time_utc")
            or item.get("start_time")
            or item.get("startTimeUTC")
            or item.get("startTimeGMT")
            or item.get("date")
        )
        metadata: dict[str, Any] = {
            "source_provider": "pulsai",
            "upstream_provider": "garmin",
            "provider_activity_id": source_id,
        }
        for key in ("name", "activity_type", "device", "data_status"):
            if item.get(key) not in (None, ""):
                metadata[key] = item[key]
        if start_time:
            metadata["source_timestamp"] = start_time.isoformat()
        if test_run:
            metadata["test_run"] = True

        # Garmin's activity id remains the cross-adapter fingerprint so a
        # PulsAI replay links to an existing direct-Garmin canonical row.
        fingerprint = source_id
        activity = _find_activity(db, user.id, fingerprint)
        was_created = activity is None
        if activity is None:
            duration = _number(item, "duration_seconds", "duration", "elapsedDuration")
            activity = Activity(
                id=uuid4(),
                user_id=user.id,
                ingest_run_id=run.id,
                start_time=start_time or now,
                duration_seconds=int(duration) if duration is not None else None,
                distance_m=_number(item, "distance_m", "distance", "totalDistance"),
                sport=item.get("activity_type") or item.get("type") or item.get("name"),
                status="completed",
                fingerprint_hash=fingerprint,
                metadata_json=metadata,
                created_at=now,
                updated_at=now,
            )
            db.add(activity)
            db.commit()
            db.refresh(activity)
            created += 1
        else:
            activity.ingest_run_id = run.id  # type: ignore[assignment]
            activity.updated_at = now  # type: ignore[assignment]

        if _find_source(db, activity.id, source_id) is None:
            db.add(
                ActivitySource(
                    id=uuid4(),
                    activity_id=activity.id,
                    provider="pulsai",
                    provider_activity_id=source_id,
                    raw_hash=source_id,
                    decision="new" if was_created else "duplicate",
                    reason="Garmin-backed activity delivered through PulsAI MCP",
                    chosen_fields=metadata,
                    raw_payload=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            linked += 1
    return created, linked


class PulsaiProvider(FitnessProvider):
    """Provider adapter backed by each athlete's private PulsAI MCP endpoint."""

    name = "pulsai"
    client_factory = PulsaiMcpClient

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """PulsAI private endpoints do not use a Fitness Pals refresh token."""
        del refresh_token
        raise NotImplementedError("PulsAI connection refresh is managed by PulsAI")

    @staticmethod
    def _connection(db: Any, user: Any) -> str:
        token = get_user_provider_token(
            db,
            user.id,
            "pulsai",
            getattr(user, "tenant_id", None),
        )
        if token is None:
            raise HTTPException(status_code=410, detail="PulsAI connection required")
        endpoint = decrypt_user_tokens(token).get("access_token")
        if not endpoint:
            raise HTTPException(status_code=410, detail="PulsAI connection required")
        return str(endpoint)

    def fetch_daily_stats(self, access_token: str, **kwargs: Any) -> Dict[str, Any]:
        """Return the requested daily health summary through PulsAI MCP."""
        del access_token
        endpoint = self._connection(kwargs["db"], kwargs["user"])
        target_date = kwargs.get("date")
        arguments = {"date": target_date} if target_date else {}
        return self.client_factory().call_tool(
            endpoint, "get_health_summary", arguments
        )

    def fetch_activities(
        self,
        access_token: str,
        since: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Fetch PulsAI activities and persist canonical Garmin-backed rows."""
        del access_token
        db = kwargs["db"]
        user = kwargs["user"]
        test_run = bool(kwargs.get("test_run", False))
        endpoint = self._connection(db, user)
        arguments: dict[str, Any] = {"limit": 200}
        parsed_since = _parse_datetime(since)
        if parsed_since:
            arguments["date_from"] = parsed_since.date().isoformat()
        arguments["date_to"] = datetime.now(timezone.utc).date().isoformat()

        run = IngestRun(
            id=uuid4(),
            provider="pulsai",
            status="running",
            started_at=datetime.now(timezone.utc),
            user_id=user.id,
            summary={"test_run": test_run} if test_run else {},
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            payload = self.client_factory().call_tool(
                endpoint, "get_activities", arguments
            )
            items = _activity_items(payload)
            created, sources = _persist_activities(
                db, user, run, items, test_run=test_run
            )
            run.status = "completed"  # type: ignore[assignment]
            run.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            run.summary = {  # type: ignore[assignment]
                "activities_received": len(items),
                "activities_created": created,
                "sources_linked": sources,
                "source_provider": "pulsai",
                "upstream_provider": "garmin",
                "data_status": payload.get("data_status"),
                "latest_available_date": payload.get("latest_available_date"),
                "test_run": test_run,
            }
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            run.status = "failed"  # type: ignore[assignment]
            run.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            db.commit()
            raise
