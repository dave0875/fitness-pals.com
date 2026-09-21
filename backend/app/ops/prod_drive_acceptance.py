"""One-shot production acceptance for per-user Google Drive archive imports.

This intentionally mutates production only by queueing archive imports for an already-authorized
athlete. It never prints provider credentials, OAuth tokens, athlete email, or user IDs.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import UUID

from app.db import SESSION_FACTORY
from app.models import Activity, ProviderApp, User, UserProviderToken
from app.models.user import UserRole
from app.services.google_drive_archive import DRIVE_READONLY_SCOPE
from app.utils.security import create_access_token

GOOGLE_DRIVE_PROVIDER = "google_drive"


class AcceptanceFailure(RuntimeError):
    """A production contract failed acceptance."""


def _normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    timeout: int = 30,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=b"" if method == "POST" else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "fitness-pals-prod-drive-acceptance/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            if response.status not in {200, 202}:
                raise AcceptanceFailure(f"{method} {url} returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise AcceptanceFailure(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"{method} {url} did not return a JSON object")
    return payload


def _poll_job(
    base_url: str,
    status_url: str,
    *,
    token: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    absolute = urllib.parse.urljoin(base_url.rstrip("/") + "/", status_url.lstrip("/"))
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _request_json(absolute, token=token)
        status = str(last.get("status") or "")
        if status == "completed":
            return last
        if status == "failed":
            error = last.get("error") or {}
            raise AcceptanceFailure(
                f"archive job failed: {error.get('type', 'error')}: {error.get('message', 'unknown')}"
            )
        time.sleep(3)
    raise AcceptanceFailure(f"archive job did not finish within {timeout_seconds}s; last={last.get('status')}")


def _provider_app_is_valid(app: ProviderApp | None, base_url: str) -> None:
    if app is None:
        raise AcceptanceFailure("google_drive provider app is absent")
    if not app.client_id or not app.client_secret_encrypted:
        raise AcceptanceFailure("google_drive provider app lacks client credentials")
    expected_redirect = f"{base_url.rstrip('/')}/api/archive-imports/google-drive/callback"
    if str(app.redirect_uri or "").rstrip("/") != expected_redirect.rstrip("/"):
        raise AcceptanceFailure("google_drive provider app redirect URI does not match production callback")
    scopes = set(str(app.scopes or "").replace(",", " ").split())
    if DRIVE_READONLY_SCOPE not in scopes:
        raise AcceptanceFailure("google_drive provider app lacks drive.readonly scope")


def _select_connected_athlete(db: Any) -> tuple[User, UserProviderToken]:
    tokens = (
        db.query(UserProviderToken)
        .filter(UserProviderToken.provider == GOOGLE_DRIVE_PROVIDER)
        .all()
    )
    candidates: list[tuple[User, UserProviderToken]] = []
    for provider_token in tokens:
        user = db.get(User, provider_token.user_id)
        if user is None:
            continue
        scopes = set(str(provider_token.scope or "").split())
        metadata_email = _normalized_email((provider_token.metadata_json or {}).get("email"))
        if DRIVE_READONLY_SCOPE not in scopes:
            continue
        if not metadata_email or metadata_email != _normalized_email(user.email):
            continue
        candidates.append((user, provider_token))
    if not candidates:
        raise AcceptanceFailure(
            "no production athlete has a matching encrypted google_drive grant; interactive consent is still required"
        )
    candidates.sort(
        key=lambda pair: (
            pair[0].role != UserRole.ADMINISTRATOR.value,
            pair[0].created_at,
        )
    )
    return candidates[0]


def _assert_job_clean(payload: dict[str, Any], *, label: str) -> int:
    failed = int(payload.get("objects_failed") or 0)
    imported = int(payload.get("objects_imported") or 0)
    skipped = int(payload.get("objects_skipped") or 0)
    if failed:
        raise AcceptanceFailure(f"{label} reported {failed} failed Drive object(s)")
    seen = imported + skipped
    if seen <= 0:
        raise AcceptanceFailure(f"{label} found no supported Garmin archive objects in Drive")
    return seen


def _assert_replay_idempotent(
    first: dict[str, Any],
    replay: dict[str, Any],
    *,
    activities_before_replay: int,
    activities_after_replay: int,
) -> None:
    first_seen = _assert_job_clean(first, label="first import")
    _assert_job_clean(replay, label="replay")
    if int(replay.get("objects_imported") or 0) != 0:
        raise AcceptanceFailure("replay imported Drive objects that should have been checkpointed")
    if int(replay.get("objects_skipped") or 0) < first_seen:
        raise AcceptanceFailure("replay did not checkpoint all Drive objects seen on the first import")
    if activities_after_replay != activities_before_replay:
        raise AcceptanceFailure("canonical activity count increased during immediate replay")


def run_acceptance(base_url: str, poll_timeout: int) -> None:
    db = SESSION_FACTORY()
    try:
        app = db.query(ProviderApp).filter(ProviderApp.provider == GOOGLE_DRIVE_PROVIDER).first()
        _provider_app_is_valid(app, base_url)
        user, _provider_token = _select_connected_athlete(db)
        token = create_access_token(UUID(str(user.id)))
        before = db.query(Activity).filter(Activity.user_id == user.id).count()
    finally:
        db.close()

    capabilities = _request_json(
        f"{base_url.rstrip('/')}/api/archive-imports/capabilities", token=token
    )
    drive = capabilities.get("drive") or {}
    if not drive.get("authorization_available") or not drive.get("connected") or not drive.get("can_import"):
        raise AcceptanceFailure("live capabilities do not report the selected athlete's Drive grant as importable")

    first_start = _request_json(
        f"{base_url.rstrip('/')}/api/archive-imports/google-drive", token=token, method="POST"
    )
    first = _poll_job(
        base_url,
        str(first_start.get("status_url") or ""),
        token=token,
        timeout_seconds=poll_timeout,
    )
    _assert_job_clean(first, label="first import")

    db = SESSION_FACTORY()
    try:
        after_first = db.query(Activity).filter(Activity.user_id == user.id).count()
    finally:
        db.close()

    replay_start = _request_json(
        f"{base_url.rstrip('/')}/api/archive-imports/google-drive", token=token, method="POST"
    )
    replay = _poll_job(
        base_url,
        str(replay_start.get("status_url") or ""),
        token=token,
        timeout_seconds=poll_timeout,
    )

    db = SESSION_FACTORY()
    try:
        after_replay = db.query(Activity).filter(Activity.user_id == user.id).count()
    finally:
        db.close()

    _assert_replay_idempotent(
        first,
        replay,
        activities_before_replay=after_first,
        activities_after_replay=after_replay,
    )

    journey = _request_json(
        f"{base_url.rstrip('/')}/api/journey?window=365d&sport=all&goal=all", token=token
    )
    if not isinstance(journey, dict):
        raise AcceptanceFailure("Journey did not return a JSON object after Drive import")

    print(
        "PASS production Google Drive OAuth archive acceptance: "
        f"initial_activity_count={before} after_first={after_first} after_replay={after_replay} "
        f"first_imported={int(first.get('objects_imported') or 0)} "
        f"first_skipped={int(first.get('objects_skipped') or 0)} "
        f"replay_skipped={int(replay.get('objects_skipped') or 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://fitness-pals.com")
    parser.add_argument("--poll-timeout", type=int, default=900)
    args = parser.parse_args()
    try:
        run_acceptance(args.base_url, args.poll_timeout)
    except AcceptanceFailure as exc:
        print(f"NO-PASS production Google Drive OAuth archive acceptance: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
