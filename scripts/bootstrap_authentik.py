#!/usr/bin/env python3
"""Idempotently bootstrap Authentik for GPT-facing OAuth."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def get_env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Return an environment variable or exit with a clear error."""
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


AUTHENTIK_API_URL = get_env(
    "AUTHENTIK_API_URL",
    get_env("AUTHENTIK_BASE_URL", "http://127.0.0.1:9100").rstrip("/") + "/api/v3",
).rstrip("/")
AUTHENTIK_TOKEN = get_env("AUTHENTIK_BOOTSTRAP_TOKEN", required=True)
AUTHENTIK_PROVIDER_NAME = get_env("AUTHENTIK_PROVIDER_NAME", "Training Agent GPT Provider")
AUTHENTIK_APP_NAME = get_env("AUTHENTIK_APP_NAME", "Training Agent GPT")
AUTHENTIK_APP_SLUG = get_env("AUTHENTIK_APP_SLUG", "training-agent-gpt")
AUTHENTIK_CLIENT_ID = get_env("RUNTRAINER_OIDC_CLIENT_ID", required=True)
AUTHENTIK_CLIENT_SECRET = get_env("RUNTRAINER_OIDC_CLIENT_SECRET", required=True)
AUTHENTIK_USER_EMAIL = get_env("AUTHENTIK_USER_EMAIL", required=True)
AUTHENTIK_USER_NAME = get_env("AUTHENTIK_USER_NAME", AUTHENTIK_USER_EMAIL)
AUTHENTIK_USER_PASSWORD = get_env("AUTHENTIK_USER_PASSWORD", required=True)
AUTHENTIK_REDIRECT_URIS = [
    entry.strip()
    for entry in get_env("AUTHENTIK_REDIRECT_URIS", required=True).split(",")
    if entry.strip()
]


def api_call(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> Any:
    """Call the Authentik API and return decoded JSON when present."""
    url = AUTHENTIK_API_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        method=method,
        data=body,
        headers={
            "Authorization": f"Bearer {AUTHENTIK_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in expected:
                raise SystemExit(f"{method} {url} returned unexpected status {response.status}")
            content = response.read().decode("utf-8").strip()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as err:
        body_text = err.read().decode("utf-8", errors="replace")
        if err.code not in expected:
            raise SystemExit(f"{method} {url} failed: {err.code} {body_text}") from err
        return json.loads(body_text) if body_text else None


def wait_for_api() -> None:
    """Wait until the Authentik API accepts authenticated requests."""
    last_error = "unknown"
    for _ in range(90):
        try:
            api_call("GET", "/flows/instances/", query={"page_size": 1})
            return
        except SystemExit as err:
            last_error = str(err)
            time.sleep(2)
    raise SystemExit(f"Authentik API did not become ready: {last_error}")


def first_result(path: str, *, query: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first result from a paginated list endpoint."""
    response = api_call("GET", path, query=query)
    results = response.get("results", [])
    return results[0] if results else None


def ensure_flow_uuid(designation: str, preferred_slugs: list[str]) -> str:
    """Find a flow UUID by designation, preferring known default slugs."""
    response = api_call(
        "GET",
        "/flows/instances/",
        query={"designation": designation, "page_size": 100},
    )
    flows = response.get("results", [])
    if not flows:
        raise SystemExit(f"No flows found for designation={designation}")
    for slug in preferred_slugs:
        for flow in flows:
            if flow.get("slug") == slug:
                return flow.get("flow_uuid") or flow["pk"]
    return flows[0].get("flow_uuid") or flows[0]["pk"]


def ensure_signing_key() -> str:
    """Return the default certificate key pair used to sign OIDC tokens."""
    response = api_call(
        "GET",
        "/crypto/certificatekeypairs/",
        query={"page_size": 100},
    )
    certificates = response.get("results", [])
    if not certificates:
        raise SystemExit("No certificate key pairs found for OIDC signing")
    for certificate in certificates:
        if certificate.get("private_key_available"):
            return certificate["pk"]
    raise SystemExit("No certificate key pair with an available private key found")


def ensure_scope_mappings(scope_names: list[str]) -> list[str]:
    """Return the property mapping PKs for the requested OIDC scopes."""
    response = api_call(
        "GET",
        "/propertymappings/provider/scope/",
        query={"page_size": 100},
    )
    mappings = response.get("results", [])
    by_scope = {mapping.get("scope_name"): mapping["pk"] for mapping in mappings}
    missing = [scope for scope in scope_names if scope not in by_scope]
    if missing:
        raise SystemExit(f"Missing Authentik scope mappings for: {', '.join(missing)}")
    return [by_scope[scope] for scope in scope_names]


def ensure_provider(
    authorization_flow: str,
    invalidation_flow: str,
    *,
    signing_key: str,
    property_mappings: list[str],
) -> dict[str, Any]:
    """Create or update the OAuth2 provider."""
    redirect_uris = []
    for entry in AUTHENTIK_REDIRECT_URIS:
        matching_mode = "strict"
        url = entry
        if entry.startswith("regex|"):
            matching_mode = "regex"
            url = entry.split("|", 1)[1]
        elif entry.startswith("strict|"):
            url = entry.split("|", 1)[1]
        redirect_uris.append({"matching_mode": matching_mode, "url": url})
    payload = {
        "name": AUTHENTIK_PROVIDER_NAME,
        "authorization_flow": authorization_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": AUTHENTIK_CLIENT_ID,
        "client_secret": AUTHENTIK_CLIENT_SECRET,
        "access_code_validity": "minutes=5",
        "access_token_validity": "hours=1",
        "refresh_token_validity": "hours=720",
        "refresh_token_threshold": "hours=24",
        "include_claims_in_id_token": True,
        "signing_key": signing_key,
        "redirect_uris": redirect_uris,
        "sub_mode": "user_email",
        "issuer_mode": "per_provider",
        "property_mappings": property_mappings,
        "jwt_federation_sources": [],
        "jwt_federation_providers": [],
    }
    existing = first_result(
        "/providers/oauth2/",
        query={"name": AUTHENTIK_PROVIDER_NAME, "page_size": 1},
    )
    if existing:
        provider_id = existing.get("id") or existing["pk"]
        return api_call(
            "PATCH",
            f"/providers/oauth2/{provider_id}/",
            payload=payload,
            expected=(200,),
        )
    return api_call("POST", "/providers/oauth2/", payload=payload, expected=(201,))


def ensure_application(provider_id: int) -> dict[str, Any]:
    """Create or update the application bound to the provider."""
    payload = {
        "name": AUTHENTIK_APP_NAME,
        "slug": AUTHENTIK_APP_SLUG,
        "provider": provider_id,
        "meta_launch_url": "https://training-api-prod.fitness-pals.com/health",
        "open_in_new_tab": True,
    }
    existing = first_result(
        "/core/applications/",
        query={"slug": AUTHENTIK_APP_SLUG, "page_size": 1},
    )
    if existing:
        return api_call(
            "PATCH",
            f"/core/applications/{existing['slug']}/",
            payload=payload,
            expected=(200,),
        )
    return api_call("POST", "/core/applications/", payload=payload, expected=(201,))


def ensure_user() -> dict[str, Any]:
    """Create or update the local Authentik user used for GPT auth."""
    payload = {
        "username": AUTHENTIK_USER_EMAIL,
        "name": AUTHENTIK_USER_NAME,
        "email": AUTHENTIK_USER_EMAIL,
        "is_active": True,
        "attributes": {},
    }
    existing = first_result(
        "/core/users/",
        query={"email": AUTHENTIK_USER_EMAIL, "page_size": 1},
    )
    if existing:
        user_id = existing.get("id") or existing["pk"]
        user = api_call(
            "PATCH",
            f"/core/users/{user_id}/",
            payload=payload,
            expected=(200,),
        )
    else:
        user = api_call("POST", "/core/users/", payload=payload, expected=(201,))
    api_call(
        "POST",
        f"/core/users/{user.get('id') or user['pk']}/set_password/",
        payload={"password": AUTHENTIK_USER_PASSWORD},
        expected=(204,),
    )
    return user


def main() -> None:
    """Bootstrap Authentik and print the provider setup URLs."""
    wait_for_api()
    authorization_flow = ensure_flow_uuid(
        "authorization",
        [
            "default-provider-authorization-implicit-consent",
            "default-provider-authorization-explicit-consent",
        ],
    )
    invalidation_flow = ensure_flow_uuid(
        "invalidation",
        ["default-provider-invalidation-flow"],
    )
    signing_key = ensure_signing_key()
    property_mappings = ensure_scope_mappings(["openid", "email", "profile"])
    provider = ensure_provider(
        authorization_flow,
        invalidation_flow,
        signing_key=signing_key,
        property_mappings=property_mappings,
    )
    provider_id = provider.get("id") or provider["pk"]
    application = ensure_application(provider_id)
    user = ensure_user()
    setup_urls = api_call(
        "GET",
        f"/providers/oauth2/{provider_id}/setup_urls/",
        expected=(200,),
    )
    print(
        json.dumps(
            {
                "provider_id": provider_id,
                "application_slug": application["slug"],
                "user_email": user["email"],
                "setup_urls": setup_urls,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
