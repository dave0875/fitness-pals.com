"""Robust FIT downloader for Garmin Connect."""

from __future__ import annotations

import logging
import zipfile
import io
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger("garmin.fit_download")
logger.setLevel(logging.INFO)


class NoFitFileError(Exception):
    """Raised when we determine definitively that no FIT file exists."""


class GarminAuthError(Exception):
    """Raised when authentication is missing/expired (Garmin may return 404)."""


def is_valid_fit_bytes(b: bytes) -> bool:
    """Basic validation to avoid passing HTML/JSON/truncated data to fitparse."""
    if not b or len(b) < 100:
        return False
    prefix = b[:5]
    if prefix.startswith(b"{") or prefix.startswith(b"[") or prefix.lower().startswith(b"null"):
        return False
    if prefix.startswith(b"<"):
        return False
    return True


def maybe_unzip_fit(fit_bytes: bytes) -> bytes:
    """If bytes are ZIP, extract first .fit entry; otherwise return original."""
    if not fit_bytes or len(fit_bytes) < 4:
        return fit_bytes
    if not fit_bytes.startswith(b"PK\x03\x04"):
        return fit_bytes
    try:
        with zipfile.ZipFile(io.BytesIO(fit_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".fit"):
                    with zf.open(name) as fh:
                        return fh.read()
    except Exception:  # pylint: disable=broad-except
        return fit_bytes
    return fit_bytes


def fetch_activity_metadata(client, activity_id) -> Optional[Dict[str, Any]]:
    """Fetch activity detail JSON; return None on failure."""
    path = f"activity-service/activity/{activity_id}"
    try:
        return client.connectapi(path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "fit metadata fetch failed",
            extra={"activity_id": activity_id, "path": path, "error": str(exc)},
            exc_info=True,
        )
        return None


def _get_type_key(meta: Dict[str, Any]) -> str:
    t = meta.get("activityType") or {}
    return (t.get("typeKey") or t.get("key") or t.get("typeId") or "").upper()


def should_expect_fit_file(metadata: Dict[str, Any]) -> bool:
    """
    Return True if a FIT file should exist for this activity.
    Rules:
      - Skip 3rd-party/manual uploads.
      - Skip wellness/sleep-only categories.
      - Otherwise assume device-recorded activity should have FIT.
    """
    if not metadata:
        return False

    upload_source = (metadata.get("uploadSource") or "").upper()
    if upload_source in {"THIRD_PARTY", "MANUAL"}:
        return False
    if metadata.get("manualActivity"):
        return False
    manufacturer = (metadata.get("manufacturer") or "").upper()
    device_id = metadata.get("deviceId")
    if not manufacturer and not device_id and upload_source == "THIRD_PARTY":
        return False

    type_key = _get_type_key(metadata)
    unsupported = {
        "SLEEP",
        "WELLNESS",
        "DAILY_SUMMARY",
        "HRV_STATUS",
        "SPO2",
        "STRESS",
        "BODY_BATTERY",
    }
    if type_key in unsupported:
        return False

    summary_detail = metadata.get("activityDetail") or {}
    if summary_detail.get("hasPolyline") is False and upload_source == "THIRD_PARTY":
        return False

    return True


def _auth_guard(client) -> None:
    token = getattr(client, "oauth2_token", None)
    if not token or getattr(token, "expired", False):
        raise GarminAuthError("OAuth2 token missing or expired")


def _signed_get_bytes(client, url: str) -> bytes:
    _auth_guard(client)
    headers = {}
    token = getattr(client, "oauth2_token", None)
    if token:
        headers["Authorization"] = str(token)
    resp = client.sess.get(url, headers=headers, timeout=getattr(client, "timeout", 10))
    if resp.status_code in (401, 403):
        raise GarminAuthError(f"Auth failed ({resp.status_code}) for {url}")
    if resp.status_code == 404:
        return b""
    resp.raise_for_status()
    return resp.content


def try_download_endpoint(client, url: str) -> Optional[bytes]:
    """
    Attempt a single endpoint.
    Returns bytes on success, None on true-not-found, raises GarminAuthError on auth issues.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc == "connectapi.garmin.com":
            path_only = parsed.path
            _auth_guard(client)
            resp = client.download(path_only)
            return resp if resp else None
        content = _signed_get_bytes(client, url)
        if content == b"":
            return None
        return content
    except GarminAuthError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        msg = str(exc)
        if "404" in msg:
            return None
        raise


def download_fit_file(client, activity_id) -> Optional[bytes]:
    """
    High-level FIT downloader:
      - inspect metadata to see if FIT should exist
      - attempt both known endpoints
      - return bytes on success, None if definitively no FIT
      - raise GarminAuthError on auth problems
    """
    meta = fetch_activity_metadata(client, activity_id) or {}
    if not should_expect_fit_file(meta):
        return None

    endpoints = [
        # Primary (works in testing)
        f"https://connectapi.garmin.com/download-service/files/activity/{activity_id}",
        # Legacy/export endpoint as fallback
        f"https://connectapi.garmin.com/download-service/export/fit/activity/{activity_id}",
        # Older gc-api host as final fallback
        f"https://connect.garmin.com/gc-api/download-service/files/activity/{activity_id}",
    ]

    last_auth_error: Optional[Exception] = None
    for url in endpoints:
        try:
            data = try_download_endpoint(client, url)
            if data:
                is_zip = data.startswith(b"PK\x03\x04")
                if is_zip:
                    logger.info(
                        "fit download zip detected",
                        extra={"activity_id": activity_id, "url": url, "len": len(data)},
                    )
                    data = maybe_unzip_fit(data)
                valid = is_valid_fit_bytes(data)
                logger.info(
                    "fit download inspected",
                    extra={
                        "activity_id": activity_id,
                        "url": url,
                        "len": len(data) if data else 0,
                        "prefix": data[:32] if data else b"",
                        "zip": is_zip,
                        "valid": valid,
                    },
                )
                if valid:
                    return data
        except GarminAuthError as exc:
            last_auth_error = exc
            break

    if last_auth_error:
        raise GarminAuthError(str(last_auth_error))

    return None
