# ruff: noqa: E501
# pylint: disable=line-too-long
"""Google OAuth helper utilities for the training agent."""
# mypy: ignore-errors

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

DEFAULT_SCOPE: str = os.environ.get("RUNTRAINER_GOOGLE_SCOPE") or "openid email profile"
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
GOOGLE_REQUEST_TIMEOUT: int = 5
TOKENINFO_URL: str = "https://oauth2.googleapis.com/tokeninfo"

logger = logging.getLogger("training_agent.oauth")

router = APIRouter()


class OAuthAuthorizeParams(BaseModel):
    """Query parameters accepted by the Google OAuth authorize proxy."""

    state: Optional[str] = None
    scope: Optional[str] = DEFAULT_SCOPE
    response_type: str = "code"
    access_type: str = "offline"
    prompt: str = "consent"
    code_challenge: Optional[str] = None
    code_challenge_method: Optional[str] = None


def verify_google_bearer(token: str, audience: str) -> dict:
    """
    Accept either a Google ID token (JWT) or an OAuth access token issued for the same client.
    - ID tokens are verified locally via google.oauth2.id_token.
    - Access tokens are verified by calling Google's tokeninfo endpoint.
    """
    request_obj = google_requests.Request()

    try:
        claims = id_token.verify_oauth2_token(token, request_obj, audience=audience)
        claims["_token_type"] = "id_token"
        return claims
    except (ValueError, google_exceptions.GoogleAuthError) as err:
        logger.info(
            "Bearer did not validate as ID token; will try access token path",
            extra={"error": str(err), "error_type": type(err).__name__},
        )

    try:
        # Some test stubs don't accept kwargs; try standard call then fall back.
        get_fn = requests.get
        try:
            resp = get_fn(
                TOKENINFO_URL,
                params={"access_token": token},
                timeout=GOOGLE_REQUEST_TIMEOUT,
            )
        except TypeError:
            resp = get_fn(TOKENINFO_URL, {"access_token": token}, GOOGLE_REQUEST_TIMEOUT)
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


def require_google_auth(
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> dict:
    """Dependency to enforce a valid Google bearer token on protected endpoints."""
    client_id = (
        GOOGLE_CLIENT_ID
        or os.environ.get("RUNTRAINER_GOOGLE_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
    )
    if not client_id:
        raise HTTPException(
            status_code=500, detail="Server missing RUNTRAINER_GOOGLE_CLIENT_ID env"
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_google_bearer(token, client_id)


@router.get("/oauth/google/auth")
def oauth_google_auth(params: OAuthAuthorizeParams = Depends()):
    """Proxy to Google's OAuth authorize endpoint for the configured client."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Server missing Google OAuth env")

    payload = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": params.response_type,
        "scope": params.scope,
        "access_type": params.access_type,
        "prompt": params.prompt,
    }
    if params.state:
        payload["state"] = params.state
    if params.code_challenge:
        payload["code_challenge"] = params.code_challenge
    if params.code_challenge_method:
        payload["code_challenge_method"] = params.code_challenge_method

    url = requests.Request("GET", GOOGLE_AUTH_URL, params=payload).prepare().url
    return RedirectResponse(url)


@router.post("/oauth/google/token")
async def oauth_google_token(request: Request):
    """Proxy to Google's token endpoint; accepts form/JSON/query and forwards with client credentials."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500, detail="Server missing Google client credentials/env"
        )

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
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
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
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

    try:
        safe_payload = dict(payload)
        if "client_secret" in safe_payload:
            safe_payload["client_secret"] = "***REDACTED***"
        logger.info("Posting token request to Google", extra={"payload": safe_payload})
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        logger.info(
            "Token response from Google",
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
