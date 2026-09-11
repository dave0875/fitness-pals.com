"""OAuth login routes for brokered and fallback providers."""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime
from typing import Optional, cast
from uuid import UUID

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import OidcIdentity, User
from app.utils.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    set_auth_cookies,
)

if hasattr(get_settings, "cache_clear"):
    get_settings.cache_clear()
settings = get_settings()
oauth = OAuth()
logger = logging.getLogger("auth.oauth")
logger.setLevel(logging.INFO)

DEFAULT_PROVIDER = "authentik"
AUTH_NEXT_COOKIE = "runtrainer_auth_next"
LEGACY_FALLBACK_PROVIDER = "google"
GOOGLE_ISSUER = "https://accounts.google.com"
LEGACY_PROVIDER_ALIASES = {
    "google": DEFAULT_PROVIDER,
    "microsoft": DEFAULT_PROVIDER,
    "apple": DEFAULT_PROVIDER,
}

_registered: dict[str, bool] = {}


def _discovery_url_for_issuer(issuer: str) -> str:
    """Build the OIDC discovery URL from an issuer base URL."""
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _oidc_issuer() -> str | None:
    """Return the website OIDC issuer, preferring web-specific config."""
    issuer = settings.web_oidc_issuer or settings.oidc_issuer
    return str(issuer) if issuer else None


def _oidc_client_id() -> str | None:
    """Return the website OIDC client ID, preferring web-specific config."""
    return settings.web_oidc_client_id or settings.oidc_client_id


def _oidc_client_secret() -> str | None:
    """Return the website OIDC client secret, preferring web-specific config."""
    return settings.web_oidc_client_secret or settings.oidc_client_secret


def _oidc_redirect_uri() -> str | None:
    """Return the website OIDC redirect URI, preferring web-specific config."""
    redirect_uri = settings.web_oidc_redirect_uri or settings.oidc_redirect_uri
    return str(redirect_uri) if redirect_uri else None


def _oidc_scope() -> str:
    """Return the website OIDC scope, preferring web-specific config."""
    return settings.web_oidc_scope or settings.oidc_scope


def _oidc_enabled() -> bool:
    """Return True when the complete brokered Authentik login is configured."""
    return all(
        [
            _oidc_issuer(),
            _oidc_client_id(),
            _oidc_client_secret(),
            _oidc_redirect_uri(),
        ]
    )


def _register_provider(
    name: str,
    metadata_url: str,
    client_id: Optional[str],
    client_secret: Optional[str],
    scope: str,
) -> None:
    """Register a provider with Authlib when credentials are available."""
    if not client_id or not client_secret:
        logger.info(
            "Skipping OAuth registration; missing client config",
            extra={"provider": name},
        )
        return
    oauth.register(
        name=name,
        server_metadata_url=metadata_url,
        client_id=client_id,
        client_secret=client_secret,
        client_kwargs={"scope": scope},
    )
    _registered[name] = True


if _oidc_enabled():
    _register_provider(
        DEFAULT_PROVIDER,
        _discovery_url_for_issuer(_oidc_issuer() or ""),
        _oidc_client_id(),
        _oidc_client_secret(),
        _oidc_scope(),
    )
else:
    if all(
        [
            settings.google_fallback_enabled,
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        ]
    ):
        _register_provider(
            "google",
            "https://accounts.google.com/.well-known/openid-configuration",
            settings.google_client_id,
            settings.google_client_secret,
            "openid email profile",
        )
    _register_provider(
        "microsoft",
        "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        settings.microsoft_client_id,
        settings.microsoft_client_secret,
        "openid email profile offline_access",
    )
    _register_provider(
        "apple",
        "https://appleid.apple.com/.well-known/openid-configuration",
        settings.apple_client_id,
        settings.apple_client_secret,
        "openid email name",
    )


router = APIRouter(prefix="/auth", tags=["auth"])


def _canonical_provider(provider: str) -> str:
    """Map legacy entry points to the active provider."""
    normalized = provider.lower()
    if _oidc_enabled():
        return LEGACY_PROVIDER_ALIASES.get(normalized, normalized)
    return normalized


def _default_provider() -> str:
    """Return the provider used by the top-level login route."""
    if _oidc_enabled():
        return DEFAULT_PROVIDER
    if settings.google_fallback_enabled:
        return LEGACY_FALLBACK_PROVIDER
    return DEFAULT_PROVIDER


def _redirect_uri_for(provider: str) -> Optional[str]:
    """Return the configured redirect URI for a given provider."""
    canonical = _canonical_provider(provider)
    if canonical == DEFAULT_PROVIDER:
        return _oidc_redirect_uri()

    mapping = {
        "google": str(settings.google_redirect_uri) if settings.google_redirect_uri else None,
        "microsoft": (
            str(settings.microsoft_redirect_uri) if settings.microsoft_redirect_uri else None
        ),
        "apple": str(settings.apple_redirect_uri) if settings.apple_redirect_uri else None,
    }
    return mapping.get(canonical)


def _trusted_issuer(provider: str) -> str | None:
    """Return the issuer whose token validation configured this provider."""
    if provider == DEFAULT_PROVIDER:
        return _oidc_issuer()
    if provider == LEGACY_FALLBACK_PROVIDER:
        return GOOGLE_ISSUER
    client = getattr(oauth, provider)
    issuer = client.server_metadata.get("issuer")
    return str(issuer) if issuer else None


def _normalized_email(userinfo) -> str:
    """Require a provider-verified email and return its canonical form."""
    if userinfo.get("email_verified") is not True:
        raise HTTPException(
            status_code=400,
            detail="OIDC provider did not return a verified email",
        )
    email = userinfo.get("email")
    if not isinstance(email, str):
        raise HTTPException(status_code=400, detail="OIDC provider did not return an email")
    normalized = unicodedata.normalize("NFKC", email).strip().casefold()
    if not normalized:
        raise HTTPException(status_code=400, detail="OIDC provider returned an empty email")
    return normalized


def _subject(userinfo) -> str:
    """Require the stable, case-sensitive OIDC subject claim."""
    subject = userinfo.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(
            status_code=400,
            detail="OIDC provider did not return a subject",
        )
    return subject


def _resolve_user(
    db: Session,
    *,
    issuer: str,
    subject: str,
    email: str,
    userinfo,
) -> User:
    """Resolve by stable identity, linking by verified normalized email once."""
    identity = (
        db.query(OidcIdentity)
        .filter(
            OidcIdentity.issuer == issuer,
            OidcIdentity.subject == subject,
        )
        .first()
    )
    now = datetime.utcnow()
    if identity:
        bound_user = identity.user
        setattr(bound_user, "last_login_at", now)
        return bound_user

    email_user: Optional[User] = (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == email)
        .first()
    )
    if (
        email_user
        and unicodedata.normalize("NFKC", email_user.email).strip().casefold()
        != email
    ):
        email_user = None
    if not email_user:
        user = User(
            email=email,
            name=userinfo.get("name"),
            picture_url=userinfo.get("picture"),
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user = email_user
        setattr(user, "email", email)
        setattr(user, "last_login_at", now)

    db.add(OidcIdentity(issuer=issuer, subject=subject, user=user))
    return user


def _safe_next_path(candidate: Optional[str], default: str = "/welcome") -> str:
    """Allow only local absolute paths for post-auth redirects."""
    if not candidate:
        return default
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    return candidate


async def _fetch_userinfo(provider: str, token, request: Request):
    """Fetch profile claims for the authenticated user."""
    client = getattr(oauth, provider)
    try:
        if "userinfo_endpoint" in client.server_metadata:
            return await client.userinfo(token=token)
    except OAuthError as exc:
        logger.warning(
            "Failed to fetch userinfo via endpoint",
            extra={"provider": provider},
            exc_info=exc,
        )
    try:
        claims = await client.parse_id_token(request, token)
        if claims:
            return claims
    except (OAuthError, ValueError) as exc:
        logger.info("ID token parse failed", extra={"provider": provider}, exc_info=exc)
    return token.get("userinfo")


def _require_provider(provider: str) -> str:
    """Ensure the provider was registered at startup and return its canonical name."""
    canonical = _canonical_provider(provider)
    if canonical not in _registered:
        raise HTTPException(
            status_code=404, detail=f"Provider {canonical} not configured"
        )
    return canonical


@router.get("/logout")
async def logout():
    """Clear the app session and return to the public home page."""
    response = RedirectResponse(url="/", status_code=303)
    clear_auth_cookies(response)
    return response


@router.get("/{provider}/login")
async def login(provider: str, request: Request):
    """Start the OAuth login flow for the selected provider."""
    provider = _require_provider(provider)
    redirect_uri = _redirect_uri_for(provider)
    if not redirect_uri:
        raise HTTPException(
            status_code=500, detail=f"Missing redirect URI for {provider}"
        )
    client = getattr(oauth, provider)
    response = await client.authorize_redirect(request, redirect_uri)
    response.set_cookie(
        AUTH_NEXT_COOKIE,
        _safe_next_path(request.query_params.get("next"), "/welcome"),
        max_age=300,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/login")
async def login_google(request: Request):
    """Backward-compatible login endpoint routed to the active auth provider."""
    return await login(_default_provider(), request)


@router.get("/{provider}/callback")
async def auth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    """Handle OAuth callback for the active provider."""
    provider = _require_provider(provider)
    client = getattr(oauth, provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    userinfo = await _fetch_userinfo(provider, token, request)
    if not userinfo:
        raise HTTPException(status_code=400, detail=f"No userinfo from {provider}")
    issuer = _trusted_issuer(provider)
    if not issuer:
        raise HTTPException(
            status_code=400,
            detail=f"No trusted issuer configured for {provider}",
        )
    email = _normalized_email(userinfo)
    subject = _subject(userinfo)
    user = _resolve_user(
        db,
        issuer=issuer,
        subject=subject,
        email=email,
        userinfo=userinfo,
    )
    db.commit()
    db.refresh(user)
    user_id_value = cast(UUID, getattr(user, "id"))
    access = create_access_token(user_id_value)
    refresh = create_refresh_token(user_id_value)
    response = RedirectResponse(
        url=_safe_next_path(request.cookies.get(AUTH_NEXT_COOKIE), "/welcome"),
        status_code=303,
    )
    set_auth_cookies(response, access, refresh)
    response.delete_cookie(AUTH_NEXT_COOKIE, path="/")
    return response


@router.get("/callback")
async def auth_callback_google(request: Request, db: Session = Depends(get_db)):
    """Backward-compatible callback endpoint routed to the active auth provider."""
    return await auth_callback(_default_provider(), request, db)
