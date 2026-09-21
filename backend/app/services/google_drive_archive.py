"""Read-only Google Drive adapter for configured athlete archive folders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import UserProviderToken
from app.services.providers import (
    ProviderTokenDetails,
    decrypt_provider_app_secret,
    decrypt_user_tokens,
    get_provider_app,
    get_user_provider_token,
    save_user_provider_token,
)


DRIVE_API = "https://www.googleapis.com/drive/v3"
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_OAUTH_SCOPES = ("openid", "email", DRIVE_READONLY_SCOPE)
GOOGLE_DRIVE_PROVIDER = "google_drive"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveArchiveObject:
    """Stable metadata needed to checkpoint and download one Drive object."""

    object_id: str
    name: str
    mime_type: str
    version: str
    modified_time: str | None
    size_bytes: int


@dataclass(frozen=True)
class DriveOAuthApp:
    """Decrypted runtime view of the shared app registration stored in Postgres."""

    client_id: str
    client_secret: str
    redirect_uri: str
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]


def _normal_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _drive_oauth_app(db: Session, *, required: bool = True) -> DriveOAuthApp | None:
    row = get_provider_app(db, GOOGLE_DRIVE_PROVIDER)
    secret = decrypt_provider_app_secret(row) if row is not None else None
    if row is None or not row.client_id or not secret or not row.redirect_uri:
        if not required:
            return None
        raise HTTPException(
            status_code=503,
            detail="Google Drive authorization is not configured",
        )
    scopes = tuple(str(row.scopes or " ".join(DRIVE_OAUTH_SCOPES)).replace(",", " ").split())
    if DRIVE_READONLY_SCOPE not in scopes:
        if not required:
            return None
        raise HTTPException(
            status_code=503,
            detail="Google Drive provider app is missing the read-only Drive scope",
        )
    return DriveOAuthApp(
        client_id=row.client_id,
        client_secret=secret,
        redirect_uri=row.redirect_uri,
        authorization_url=row.auth_url or GOOGLE_AUTHORIZATION_URL,
        token_url=row.token_url or GOOGLE_TOKEN_URL,
        scopes=scopes,
    )


def google_drive_oauth_configured(db: Session) -> bool:
    """Return whether Postgres contains a complete encrypted Drive app registration."""
    return _drive_oauth_app(db, required=False) is not None


def google_drive_authorization_url(
    db: Session, *, state: str, login_hint: str
) -> str:
    """Build consent for the signed-in Google address and read-only Drive scope."""
    app = _drive_oauth_app(db)
    assert app is not None
    query = urlencode(
        {
            "response_type": "code",
            "client_id": app.client_id,
            "redirect_uri": app.redirect_uri,
            "scope": " ".join(app.scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "login_hint": _normal_email(login_hint),
        }
    )
    return f"{app.authorization_url}?{query}"


def require_matching_google_account(user: Any, profile: dict[str, Any]) -> tuple[str, str]:
    """Bind a Drive grant only when Google verifies the app user's current email."""
    if profile.get("email_verified") is not True and profile.get("verified_email") is not True:
        raise HTTPException(status_code=400, detail="Google did not return a verified email")
    granted_email = _normal_email(profile.get("email"))
    if not granted_email or granted_email != _normal_email(getattr(user, "email", None)):
        raise HTTPException(
            status_code=403,
            detail="Authorize Drive with the same Google account used to sign in",
        )
    subject = str(profile.get("sub") or profile.get("id") or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Google did not return an account identifier")
    return granted_email, subject


def exchange_google_drive_code(
    db: Session, code: str, *, http_client: httpx.Client | None = None
) -> dict[str, Any]:
    """Exchange one authorization code at Google's token endpoint."""
    app = _drive_oauth_app(db)
    assert app is not None
    client = http_client or httpx.Client(timeout=20.0)
    response = client.post(
        app.token_url,
        data={
            "code": code,
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "redirect_uri": app.redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail="Google Drive authorization failed") from exc
    payload = response.json()
    if not payload.get("access_token"):
        raise HTTPException(status_code=400, detail="Google did not return a Drive access token")
    granted_scopes = set(str(payload.get("scope") or "").split())
    if DRIVE_READONLY_SCOPE not in granted_scopes:
        raise HTTPException(status_code=400, detail="Google Drive read permission was not granted")
    return payload


def fetch_google_profile(
    access_token: str, *, http_client: httpx.Client | None = None
) -> dict[str, Any]:
    """Read the Google identity attached to the newly granted Drive token."""
    client = http_client or httpx.Client(timeout=20.0)
    response = client.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail="Google account verification failed") from exc
    return dict(response.json())


def save_google_drive_grant(
    db: Session,
    user: Any,
    token_payload: dict[str, Any],
    profile: dict[str, Any],
) -> UserProviderToken:
    """Validate and encrypt one athlete's Google Drive grant."""
    email, subject = require_matching_google_account(user, profile)
    existing = get_user_provider_token(db, user.id, GOOGLE_DRIVE_PROVIDER)
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token and existing is not None:
        refresh_token = decrypt_user_tokens(existing).get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 0)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
    return save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=user.id,
            provider=GOOGLE_DRIVE_PROVIDER,
            provider_user_id=subject,
            access_token=str(token_payload["access_token"]),
            refresh_token=str(refresh_token) if refresh_token else None,
            scope=str(token_payload.get("scope") or " ".join(DRIVE_OAUTH_SCOPES)),
            expires_at=expires_at,
            metadata={"email": email},
        ),
    )


def get_user_google_drive_grant(db: Session, user: Any) -> UserProviderToken | None:
    """Return only a grant still bound to this athlete's current email and scope."""
    token = get_user_provider_token(db, user.id, GOOGLE_DRIVE_PROVIDER)
    if token is None:
        return None
    metadata_email = _normal_email((token.metadata_json or {}).get("email"))
    scopes = set(str(token.scope or "").split())
    if metadata_email != _normal_email(getattr(user, "email", None)):
        return None
    if DRIVE_READONLY_SCOPE not in scopes:
        return None
    return token


def configured_folder_for_user(user: Any, *, settings: Any | None = None) -> str:
    """Resolve a folder from the server-side email mapping, never request input."""
    configured = settings or get_settings()
    try:
        sources = json.loads(configured.google_drive_archive_sources_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Google Drive archive sources are invalid") from exc
    if not isinstance(sources, dict):
        raise HTTPException(status_code=503, detail="Google Drive archive sources are invalid")
    source = sources.get(_normal_email(getattr(user, "email", None)))
    folder_id = source.get("folder_id") if isinstance(source, dict) else source
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise HTTPException(
            status_code=404,
            detail="Google Drive archive is not configured for this athlete",
        )
    return folder_id.strip()


def _credentials(settings: Any):
    info = None
    if settings.google_drive_service_account_json:
        try:
            info = json.loads(settings.google_drive_service_account_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google Drive service account JSON is invalid") from exc
    if info:
        return service_account.Credentials.from_service_account_info(
            info, scopes=[DRIVE_READONLY_SCOPE]
        )
    if settings.google_drive_service_account_file:
        credential_path = Path(settings.google_drive_service_account_file)
        return service_account.Credentials.from_service_account_file(
            str(credential_path), scopes=[DRIVE_READONLY_SCOPE]
        )
    raise RuntimeError("Google Drive service account credentials are not configured")


class GoogleDriveArchiveClient:
    """Small Drive v3 client limited to listing and downloading archive objects."""

    def __init__(
        self,
        *,
        settings: Any | None = None,
        http_client: httpx.Client | None = None,
        credentials: Any | None = None,
        refresh_callback: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.credentials = credentials or _credentials(self.settings)
        self.refresh_callback = refresh_callback
        self.http = http_client or httpx.Client(timeout=60.0)

    @classmethod
    def for_user(
        cls,
        db: Session,
        user: Any,
        *,
        settings: Any | None = None,
        http_client: httpx.Client | None = None,
    ) -> "GoogleDriveArchiveClient":
        """Create a Drive client from this athlete's encrypted OAuth grant."""
        configured = settings or get_settings()
        app = _drive_oauth_app(db)
        assert app is not None
        token_row = get_user_google_drive_grant(db, user)
        if token_row is None:
            raise RuntimeError("Google Drive is not authorized for this athlete")
        token = decrypt_user_tokens(token_row)
        credentials = user_credentials.Credentials(
            token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            token_uri=app.token_url,
            client_id=app.client_id,
            client_secret=app.client_secret,
            scopes=str(token.get("scope") or "").split() or list(DRIVE_OAUTH_SCOPES),
        )
        expiry = token.get("expires_at")
        if expiry is not None and expiry.tzinfo is not None:
            expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
        credentials.expiry = expiry

        def persist_refresh() -> None:
            save_user_provider_token(
                db,
                ProviderTokenDetails(
                    user_id=user.id,
                    provider=GOOGLE_DRIVE_PROVIDER,
                    provider_user_id=token_row.provider_user_id,
                    access_token=credentials.token,
                    refresh_token=credentials.refresh_token,
                    scope=token_row.scope,
                    expires_at=credentials.expiry,
                    metadata=token_row.metadata_json or {},
                ),
            )

        return cls(
            settings=configured,
            http_client=http_client,
            credentials=credentials,
            refresh_callback=persist_refresh,
        )

    def _headers(self) -> dict[str, str]:
        if not self.credentials.valid:
            self.credentials.refresh(Request())
            if self.refresh_callback:
                self.refresh_callback()
        return {"Authorization": f"Bearer {self.credentials.token}"}

    def _children(self, folder_id: str) -> list[dict[str, Any]]:
        page_token = None
        children: list[dict[str, Any]] = []
        while True:
            params: dict[str, str | int] = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": (
                    "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)"
                ),
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self.http.get(
                f"{DRIVE_API}/files", params=params, headers=self._headers()
            )
            response.raise_for_status()
            payload = response.json()
            children.extend(payload.get("files") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return children

    @staticmethod
    def _supported(
        item: dict[str, Any],
        *,
        path: tuple[str, ...] = (),
        root_scoped: bool = False,
    ) -> bool:
        """Return only objects that can represent Garmin activities.

        Legacy server-mapped folders retain the broad extension contract because the
        operator already scopes those folders. Per-user OAuth starts at Drive root,
        so it must use folder/file context instead of treating every Garmin FIT file
        (sleep, HRV, metrics, monitor data, etc.) as an activity.
        """
        name = str(item.get("name") or "").lower()
        mime_type = str(item.get("mimeType") or "").lower()
        if name.endswith("_summarizedactivities.json"):
            return True
        if not root_scoped:
            return (
                name.endswith(".fit")
                or name.endswith(".zip")
                or mime_type in {"application/fits", "application/zip"}
            )

        path_segments = {segment.strip().lower() for segment in path}
        if name.endswith(".fit") or mime_type == "application/fits":
            return name.endswith("_activity.fit") or "activity" in path_segments
        if name.endswith(".zip") or mime_type in {
            "application/zip",
            "application/x-zip",
            "application/x-zip-compressed",
        }:
            return (
                name.startswith("uploadedfiles_")
                or "di-connect-uploaded-files" in path_segments
            )
        return False

    def list_supported_objects(self, folder_id: str) -> list[DriveArchiveObject]:
        """Walk a configured folder and return importable objects deterministically."""
        root_scoped = folder_id == "root"
        pending: list[tuple[str, tuple[str, ...]]] = [(folder_id, ())]
        visited: set[str] = set()
        objects: list[DriveArchiveObject] = []
        maximum = int(self.settings.google_drive_archive_max_objects)
        while pending:
            current, path = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for item in self._children(current):
                if item.get("mimeType") == FOLDER_MIME_TYPE:
                    pending.append(
                        (str(item["id"]), (*path, str(item.get("name") or item["id"])))
                    )
                    continue
                if not self._supported(item, path=path, root_scoped=root_scoped):
                    continue
                version = str(item.get("md5Checksum") or item.get("modifiedTime") or item["id"])
                objects.append(
                    DriveArchiveObject(
                        object_id=str(item["id"]),
                        name=str(item.get("name") or item["id"]),
                        mime_type=str(item.get("mimeType") or "application/octet-stream"),
                        version=version,
                        modified_time=item.get("modifiedTime"),
                        size_bytes=int(item.get("size") or 0),
                    )
                )
                if len(objects) > maximum:
                    raise RuntimeError("Google Drive archive exceeds configured object limit")
        return sorted(objects, key=lambda item: (item.modified_time or "", item.name, item.object_id))

    def download(self, item: DriveArchiveObject) -> bytes:
        response = self.http.get(
            f"{DRIVE_API}/files/{item.object_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.content
