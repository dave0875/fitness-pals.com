# ruff: noqa: E501
# pylint: disable=line-too-long
"""OAuth helper utilities for the training agent."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

import jwt
import requests  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

DEFAULT_SCOPE: str = os.environ.get("RUNTRAINER_GOOGLE_SCOPE") or "openid email profile"
OIDC_SCOPE: str = (
    os.environ.get("RUNTRAINER_OIDC_SCOPE")
    or os.environ.get("OIDC_SCOPE")
    or "openid email profile"
)
GOOGLE_AUTH_URL: str = (
    os.environ.get("RUNTRAINER_GOOGLE_AUTH_URL")
    or os.environ.get("GOOGLE_AUTH_URL")
    or "https://accounts.google.com/o/oauth2/v2/auth"
)
GOOGLE_TOKEN_URL: str = (
    os.environ.get("RUNTRAINER_GOOGLE_TOKEN_URL")
    or os.environ.get("GOOGLE_TOKEN_URL")
    or "https://oauth2.googleapis.com/token"
)
GOOGLE_CLIENT_ID: str | None = os.environ.get(
    "RUNTRAINER_GOOGLE_CLIENT_ID"
) or os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str | None = os.environ.get(
    "RUNTRAINER_GOOGLE_CLIENT_SECRET"
) or os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI: str = (
    os.environ.get("RUNTRAINER_GOOGLE_REDIRECT_URI")
    or os.environ.get("GOOGLE_REDIRECT_URI")
    or "https://chat.openai.com/aip/g-11e1b5846d447ba53af301061856b1a079cb91b9/oauth/callback"
)
OIDC_ISSUER: str | None = (
    os.environ.get("RUNTRAINER_OIDC_ISSUER") or os.environ.get("OIDC_ISSUER")
)
OIDC_AUTH_URL: str | None = (
    os.environ.get("RUNTRAINER_OIDC_AUTH_URL") or os.environ.get("OIDC_AUTH_URL")
)
OIDC_TOKEN_URL: str | None = (
    os.environ.get("RUNTRAINER_OIDC_TOKEN_URL") or os.environ.get("OIDC_TOKEN_URL")
)
OIDC_JWKS_URL: str | None = (
    os.environ.get("RUNTRAINER_OIDC_JWKS_URL") or os.environ.get("OIDC_JWKS_URL")
)
OIDC_CLIENT_ID: str | None = (
    os.environ.get("RUNTRAINER_OIDC_CLIENT_ID") or os.environ.get("OIDC_CLIENT_ID")
)
OIDC_CLIENT_SECRET: str | None = (
    os.environ.get("RUNTRAINER_OIDC_CLIENT_SECRET")
    or os.environ.get("OIDC_CLIENT_SECRET")
)
GOOGLE_REQUEST_TIMEOUT: int = 5
TOKENINFO_URL: str = "https://oauth2.googleapis.com/tokeninfo"
OPENAI_REDIRECT_HOSTS = {"chat.openai.com", "chatgpt.com"}
OPENAI_REDIRECT_PATH = re.compile(r"^/aip/[^/]+/oauth/callback$")

logger = logging.getLogger("training_agent.oauth")

router = APIRouter()


@dataclass(frozen=True)
class RuntimeAuthConfig:
    """Runtime auth configuration resolved from the current environment."""

    default_scope: str
    oidc_scope: str
    google_auth_url: str
    google_token_url: str
    google_client_id: str | None
    google_client_secret: str | None
    google_redirect_uri: str
    oidc_issuer: str | None
    oidc_auth_url: str | None
    oidc_token_url: str | None
    oidc_jwks_url: str | None
    oidc_client_id: str | None
    oidc_client_secret: str | None


class OAuthAuthorizeParams(BaseModel):
    """Query parameters accepted by the Google OAuth authorize proxy."""

    state: Optional[str] = None
    scope: Optional[str] = DEFAULT_SCOPE
    response_type: str = "code"
    access_type: str = "offline"
    prompt: str = "consent"
    redirect_uri: Optional[str] = None
    code_challenge: Optional[str] = None
    code_challenge_method: Optional[str] = None


def _runtime_env_value(*keys: str, default: str | None = None) -> str | None:
    """Return the first non-empty runtime environment value for the provided keys."""
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _current_auth_config() -> RuntimeAuthConfig:
    """Resolve effective auth settings from the current process environment."""
    return RuntimeAuthConfig(
        default_scope=_runtime_env_value("RUNTRAINER_GOOGLE_SCOPE", default=DEFAULT_SCOPE) or DEFAULT_SCOPE,
        oidc_scope=_runtime_env_value("RUNTRAINER_OIDC_SCOPE", "OIDC_SCOPE", default=OIDC_SCOPE) or OIDC_SCOPE,
        google_auth_url=_runtime_env_value(
            "RUNTRAINER_GOOGLE_AUTH_URL",
            "GOOGLE_AUTH_URL",
            default=GOOGLE_AUTH_URL,
        )
        or GOOGLE_AUTH_URL,
        google_token_url=_runtime_env_value(
            "RUNTRAINER_GOOGLE_TOKEN_URL",
            "GOOGLE_TOKEN_URL",
            default=GOOGLE_TOKEN_URL,
        )
        or GOOGLE_TOKEN_URL,
        google_client_id=_runtime_env_value("RUNTRAINER_GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID"),
        google_client_secret=_runtime_env_value(
            "RUNTRAINER_GOOGLE_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ),
        google_redirect_uri=_runtime_env_value(
            "RUNTRAINER_GOOGLE_REDIRECT_URI",
            "GOOGLE_REDIRECT_URI",
            default=GOOGLE_REDIRECT_URI,
        )
        or GOOGLE_REDIRECT_URI,
        oidc_issuer=_runtime_env_value("RUNTRAINER_OIDC_ISSUER", "OIDC_ISSUER"),
        oidc_auth_url=_runtime_env_value("RUNTRAINER_OIDC_AUTH_URL", "OIDC_AUTH_URL"),
        oidc_token_url=_runtime_env_value("RUNTRAINER_OIDC_TOKEN_URL", "OIDC_TOKEN_URL"),
        oidc_jwks_url=_runtime_env_value("RUNTRAINER_OIDC_JWKS_URL", "OIDC_JWKS_URL"),
        oidc_client_id=_runtime_env_value("RUNTRAINER_OIDC_CLIENT_ID", "OIDC_CLIENT_ID"),
        oidc_client_secret=_runtime_env_value(
            "RUNTRAINER_OIDC_CLIENT_SECRET",
            "OIDC_CLIENT_SECRET",
        ),
    )


def _oidc_enabled(config: RuntimeAuthConfig | None = None) -> bool:
    """Return True when the Authentik-backed OIDC broker is configured."""
    resolved = config or _current_auth_config()
    return bool(
        resolved.oidc_client_id
        and (
            resolved.oidc_issuer
            or resolved.oidc_auth_url
            or resolved.oidc_token_url
            or resolved.oidc_jwks_url
        )
    )


def _active_client_id(config: RuntimeAuthConfig | None = None) -> str | None:
    """Return the active client ID for the current auth backend."""
    resolved = config or _current_auth_config()
    return resolved.oidc_client_id or resolved.google_client_id


def _active_scope(config: RuntimeAuthConfig | None = None) -> str:
    """Return the scope used for the current auth backend."""
    resolved = config or _current_auth_config()
    return resolved.oidc_scope if _oidc_enabled(resolved) else resolved.default_scope


def _oidc_discovery_url(issuer: str) -> str:
    """Build the OIDC discovery URL from an issuer base URL."""
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


@lru_cache(maxsize=4)
def _load_oidc_discovery(issuer: str) -> dict:
    """Load and cache OIDC discovery metadata from the configured issuer."""
    discovery_url = _oidc_discovery_url(issuer)
    try:
        response = requests.get(discovery_url, timeout=GOOGLE_REQUEST_TIMEOUT)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="OIDC discovery failed")
        payload = response.json()
    except HTTPException:
        raise
    except (requests.RequestException, ValueError) as err:
        logger.error(
            "OIDC discovery failed",
            extra={"issuer": issuer, "error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=502, detail="OIDC discovery failed") from err
    return payload


def _oidc_discovery_metadata(config: RuntimeAuthConfig | None = None) -> dict:
    """Return discovery metadata when an issuer is configured."""
    resolved = config or _current_auth_config()
    if not resolved.oidc_issuer:
        return {}
    return _load_oidc_discovery(resolved.oidc_issuer)


def _resolved_oidc_auth_url(config: RuntimeAuthConfig | None = None) -> str | None:
    """Return the effective OIDC authorize endpoint."""
    resolved = config or _current_auth_config()
    if resolved.oidc_auth_url:
        return resolved.oidc_auth_url
    return _oidc_discovery_metadata(resolved).get("authorization_endpoint")


def _resolved_oidc_token_url(config: RuntimeAuthConfig | None = None) -> str | None:
    """Return the effective OIDC token endpoint."""
    resolved = config or _current_auth_config()
    if resolved.oidc_token_url:
        return resolved.oidc_token_url
    return _oidc_discovery_metadata(resolved).get("token_endpoint")


def _resolved_oidc_jwks_url(config: RuntimeAuthConfig | None = None) -> str | None:
    """Return the effective OIDC JWKS endpoint."""
    resolved = config or _current_auth_config()
    if resolved.oidc_jwks_url:
        return resolved.oidc_jwks_url
    return _oidc_discovery_metadata(resolved).get("jwks_uri")


def _is_allowed_openai_redirect_uri(redirect_uri: str) -> bool:
    """Allow only OpenAI-hosted OAuth callbacks for GPT app flows."""
    parsed = urlparse(redirect_uri)
    return (
        parsed.scheme == "https"
        and parsed.hostname in OPENAI_REDIRECT_HOSTS
        and bool(OPENAI_REDIRECT_PATH.match(parsed.path))
        and not parsed.params
        and not parsed.fragment
    )


def _resolve_redirect_uri(
    requested_redirect_uri: Optional[str],
    configured_redirect_uri: str,
) -> str:
    """Use the caller-supplied ChatGPT callback when valid, else the configured default."""
    redirect_uri = requested_redirect_uri or configured_redirect_uri
    if not redirect_uri or not _is_allowed_openai_redirect_uri(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")
    return redirect_uri


@lru_cache(maxsize=2)
def _get_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Return a cached JWK client for JWT validation."""
    return jwt.PyJWKClient(jwks_url)


def verify_oidc_bearer(token: str, audience: str) -> dict:
    """Validate an Authentik-issued bearer token."""
    config = _current_auth_config()
    jwks_url = _resolved_oidc_jwks_url(config)
    if not config.oidc_issuer or not jwks_url:
        raise HTTPException(status_code=500, detail="Server missing OIDC issuer configuration")
    try:
        signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=audience,
            issuer=config.oidc_issuer,
            options={"require": ["exp", "iat", "iss"]},
        )
        claims["_token_type"] = "jwt"
        claims["_provider"] = "oidc"
        return claims
    except jwt.PyJWTError as err:
        logger.info(
            "OIDC bearer validation failed",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid OIDC token") from err


def verify_google_bearer(token: str, audience: str) -> dict:
    """
    Accept either a Google ID token (JWT) or an OAuth access token issued for the same client.
    - ID tokens are verified locally via google.oauth2.id_token.
    - Access tokens are verified by calling Google's tokeninfo endpoint.
    """
    # Allow tests to monkeypatch tokens/HTTP via the main module.
    from services.training_agent import main as training_main  # pylint: disable=import-outside-toplevel

    token_verifier = getattr(training_main, "id_token", id_token)
    requests_module = getattr(training_main, "requests", requests)
    request_obj = google_requests.Request()

    try:
        claims = token_verifier.verify_oauth2_token(token, request_obj, audience=audience)
        claims["_token_type"] = "id_token"
        return claims
    except (ValueError, google_exceptions.GoogleAuthError) as err:
        logger.info(
            "Bearer did not validate as ID token; will try access token path",
            extra={"error": str(err), "error_type": type(err).__name__},
        )

    try:
        try:
            resp = requests_module.get(
                TOKENINFO_URL,
                params={"access_token": token},
                timeout=GOOGLE_REQUEST_TIMEOUT,
            )
        except TypeError:
            # Test doubles may not accept keyword args; retry positionally.
            resp = requests_module.get(TOKENINFO_URL, {"access_token": token}, GOOGLE_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(
                "tokeninfo request failed",
                extra={"status_code": resp.status_code, "body": resp.text[:200]},
            )
            raise HTTPException(status_code=401, detail="Invalid Google token")
        data = resp.json()
        if data.get("aud") != audience:
            logger.warning(
                "Access token audience mismatch",
                extra={"expected": audience, "got": data.get("aud")},
            )
            raise HTTPException(status_code=401, detail="Invalid Google token")
        data["_token_type"] = "access_token"
        return data
    except requests.RequestException as err:
        logger.error(
            "Access token validation request failed",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid Google token") from err
    except RuntimeError as err:
        logger.error(
            "Access token validation encountered runtime error",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid Google token") from err
    except ValueError as err:
        logger.error(
            "Access token validation failed",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid Google token") from err


def verify_bearer(token: str, audience: str) -> dict:
    """Validate a bearer token against OIDC first, then Google as migration fallback."""
    config = _current_auth_config()
    google_client_id = config.google_client_id
    oidc_error: HTTPException | None = None
    if _oidc_enabled(config):
        try:
            return verify_oidc_bearer(token, audience)
        except HTTPException as err:
            oidc_error = err
            if not google_client_id:
                raise
    if google_client_id:
        return verify_google_bearer(token, audience)
    if oidc_error is not None:
        raise oidc_error
    raise HTTPException(status_code=500, detail="Server missing auth configuration")


def require_google_auth(
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> dict:
    """Dependency to enforce a valid bearer token on protected endpoints."""
    from services.training_agent import main as training_main  # pylint: disable=import-outside-toplevel
    config = _current_auth_config()
    client_id = _active_client_id(config)
    if not client_id:
        raise HTTPException(status_code=500, detail="Server missing auth client configuration")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    verifier = getattr(training_main, "verify_bearer", verify_bearer)
    return verifier(token, client_id)


@router.get("/oauth/google/auth")
def oauth_google_auth(params: OAuthAuthorizeParams = Depends()):
    """Proxy to the configured OAuth authorize endpoint for GPT actions."""
    config = _current_auth_config()
    redirect_uri = _resolve_redirect_uri(params.redirect_uri, config.google_redirect_uri)
    client_id = config.oidc_client_id or config.google_client_id
    authorize_url = _resolved_oidc_auth_url(config) or config.google_auth_url
    if not client_id or not authorize_url:
        raise HTTPException(status_code=500, detail="Server missing OAuth authorize configuration")

    payload = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": params.response_type,
        "scope": params.scope or _active_scope(config),
        "access_type": params.access_type,
        "prompt": params.prompt,
    }
    if params.state:
        payload["state"] = params.state
    if params.code_challenge:
        payload["code_challenge"] = params.code_challenge
    if params.code_challenge_method:
        payload["code_challenge_method"] = params.code_challenge_method

    url = requests.Request("GET", authorize_url, params=payload).prepare().url
    if url is None:
        raise HTTPException(status_code=500, detail="Failed to construct OAuth authorize URL")
    return RedirectResponse(url)


@router.post("/oauth/google/token")
async def oauth_google_token(request: Request):
    """Proxy to the configured OAuth token endpoint; accepts form/JSON/query and forwards client credentials."""
    config = _current_auth_config()
    client_id = config.oidc_client_id or config.google_client_id
    client_secret = config.oidc_client_secret or config.google_client_secret
    token_url = _resolved_oidc_token_url(config) or config.google_token_url
    if not client_id or not client_secret or not token_url:
        raise HTTPException(status_code=500, detail="Server missing OAuth token configuration")

    data: dict = {}
    try:
        form = await request.form()
        data = dict(form)
    except (ValueError, RuntimeError) as err:
        logger.warning(
            "Form parse failed",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError, RuntimeError) as err2:
            logger.warning(
                "JSON parse failed",
                extra={"error": str(err2), "error_type": type(err2).__name__},
            )
            data = {}
    if not data:
        data = dict(request.query_params)

    logger.info(
        "Incoming token request",
        extra={
            "data": data,
            "data_keys": list(data.keys()),
            "query_keys": list(request.query_params.keys()),
        },
    )

    code = data.get("code") or request.query_params.get("code")
    grant_type = data.get("grant_type", "authorization_code")
    code_verifier = data.get("code_verifier")
    refresh_token = data.get("refresh_token")
    requested_redirect_uri = data.get("redirect_uri") or request.query_params.get("redirect_uri")
    redirect_uri = _resolve_redirect_uri(requested_redirect_uri, config.google_redirect_uri)

    if grant_type == "refresh_token":
        if not refresh_token:
            logger.info(
                "Refresh token request missing refresh_token", extra={"data": data}
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "refresh_token is required",
                },
            )
        payload = {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }
    else:
        if not code:
            logger.info("Token request missing code", extra={"data": data})
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "code is required",
                },
            )
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

    try:
        safe_payload = dict(payload)
        if "client_secret" in safe_payload:
            safe_payload["client_secret"] = "***REDACTED***"
        logger.info("Posting token request to upstream provider", extra={"payload": safe_payload})
        resp = requests.post(
            token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        logger.info(
            "Token response from upstream provider",
            extra={"status_code": resp.status_code, "response_body": resp.text},
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except requests.RequestException as err:
        logger.error("Token exchange failed (request)", exc_info=err)
        return JSONResponse(
            status_code=502,
            content={"error": "token_exchange_failed", "error_description": str(err)},
        )
    except (ValueError, json.JSONDecodeError) as err:
        logger.error("Token exchange failed (unexpected)", exc_info=err)
        return JSONResponse(
            status_code=500,
            content={"error": "token_exchange_failed", "error_description": str(err)},
        )
