#!/usr/bin/env python3
"""Idempotently bootstrap Authentik OIDC clients and upstream Google federation."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


GOOGLE_WELL_KNOWN_URL = "https://accounts.google.com/.well-known/openid-configuration"


def get_env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Return an environment variable or exit with a clear error."""
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def _is_placeholder(value: str) -> bool:
    """Return whether a deployment value is still a documented placeholder."""
    return value.strip().lower() in {"replace-me", "changeme", "placeholder"}


@dataclass(frozen=True)
class GoogleSourceConfig:
    """Desired Authentik upstream Google source configuration."""

    client_id: str | None
    client_secret: str | None
    credential_source: str
    name: str = "Google"
    slug: str = "google"
    authentication_flow_slug: str = "default-source-authentication"
    enrollment_flow_slug: str = "default-source-enrollment"
    login_flow_slug: str = "default-authentication-flow"


@dataclass(frozen=True)
class OIDCApplicationConfig:
    """Desired Authentik OAuth2 provider and application configuration."""

    provider_name: str
    app_name: str
    app_slug: str
    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...]
    meta_launch_url: str
    policy_engine_mode: str


@dataclass(frozen=True)
class OIDCClientConfig(OIDCApplicationConfig):
    """GPT-facing Authentik OIDC client plus its break-glass local user."""

    user_email: str
    user_name: str
    user_password: str


def _credential_pair(
    client_id_name: str,
    client_secret_name: str,
) -> tuple[str, str] | None:
    """Load one complete credential pair without mixing sources."""
    client_id = get_env(client_id_name).strip()
    client_secret = get_env(client_secret_name).strip()
    if bool(client_id) != bool(client_secret):
        raise SystemExit(
            f"{client_id_name} and {client_secret_name} must be set together"
        )
    if not client_id:
        return None
    if _is_placeholder(client_id) or _is_placeholder(client_secret):
        raise SystemExit(
            f"OAuth credential pair {client_id_name}/{client_secret_name} "
            "still contains a placeholder value"
        )
    return client_id, client_secret


def load_google_source_config() -> GoogleSourceConfig:
    """Load dedicated Google credentials when supplied for create or rotation."""
    dedicated = _credential_pair(
        "AUTHENTIK_GOOGLE_CLIENT_ID",
        "AUTHENTIK_GOOGLE_CLIENT_SECRET",
    )
    client_id: str | None
    client_secret: str | None
    if dedicated:
        client_id, client_secret = dedicated
        credential_source = "AUTHENTIK_GOOGLE_CLIENT_ID/AUTHENTIK_GOOGLE_CLIENT_SECRET"
    else:
        client_id = client_secret = None
        credential_source = "existing Authentik Google source (credentials retained)"
    return GoogleSourceConfig(
        client_id=client_id,
        client_secret=client_secret,
        credential_source=credential_source,
        name=get_env("AUTHENTIK_GOOGLE_SOURCE_NAME", "Google"),
        slug=get_env("AUTHENTIK_GOOGLE_SOURCE_SLUG", "google"),
        authentication_flow_slug=get_env(
            "AUTHENTIK_GOOGLE_AUTHENTICATION_FLOW_SLUG",
            "default-source-authentication",
        ),
        enrollment_flow_slug=get_env(
            "AUTHENTIK_GOOGLE_ENROLLMENT_FLOW_SLUG",
            "default-source-enrollment",
        ),
        login_flow_slug=get_env(
            "AUTHENTIK_LOGIN_FLOW_SLUG",
            "default-authentication-flow",
        ),
    )


def load_oidc_client_config() -> OIDCClientConfig:
    """Load the original GPT OIDC provider/application/local-user settings."""
    redirect_uris = tuple(
        entry.strip()
        for entry in get_env("AUTHENTIK_REDIRECT_URIS", required=True).split(",")
        if entry.strip()
    )
    if not redirect_uris:
        raise SystemExit("AUTHENTIK_REDIRECT_URIS must contain at least one redirect URI")
    user_email = get_env("AUTHENTIK_USER_EMAIL", required=True)
    return OIDCClientConfig(
        provider_name=get_env(
            "AUTHENTIK_PROVIDER_NAME",
            "Training Agent GPT Provider",
        ),
        app_name=get_env("AUTHENTIK_APP_NAME", "Training Agent GPT"),
        app_slug=get_env("AUTHENTIK_APP_SLUG", "training-agent-gpt"),
        client_id=get_env("RUNTRAINER_OIDC_CLIENT_ID", required=True),
        client_secret=get_env("RUNTRAINER_OIDC_CLIENT_SECRET", required=True),
        redirect_uris=redirect_uris,
        meta_launch_url="https://training-api-prod.fitness-pals.com/health",
        policy_engine_mode="all",
        user_email=user_email,
        user_name=get_env("AUTHENTIK_USER_NAME", user_email),
        user_password=get_env("AUTHENTIK_USER_PASSWORD", required=True),
    )


def load_grafana_oidc_config() -> OIDCApplicationConfig:
    """Load the dedicated Grafana/Authentik OIDC client settings."""
    credentials = _credential_pair(
        "GRAFANA_OIDC_CLIENT_ID",
        "GRAFANA_OIDC_CLIENT_SECRET",
    )
    if not credentials:
        raise SystemExit(
            "Missing Grafana OIDC credentials: set GRAFANA_OIDC_CLIENT_ID and "
            "GRAFANA_OIDC_CLIENT_SECRET"
        )
    client_id, client_secret = credentials
    root_url = get_env(
        "GRAFANA_ROOT_URL", "https://grafana.fitness-pals.com"
    ).rstrip("/")
    return OIDCApplicationConfig(
        provider_name=get_env("GRAFANA_OIDC_PROVIDER_NAME", "Grafana"),
        app_name=get_env("GRAFANA_OIDC_APP_NAME", "Grafana"),
        app_slug=get_env("GRAFANA_OIDC_APP_SLUG", "grafana"),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=(f"{root_url}/login/generic_oauth",),
        meta_launch_url=root_url,
        policy_engine_mode="all",
    )


def _authentik_api_url() -> str:
    """Return the configured v3 API root."""
    return get_env(
        "AUTHENTIK_API_URL",
        get_env("AUTHENTIK_BASE_URL", "http://127.0.0.1:9100").rstrip("/")
        + "/api/v3",
    ).rstrip("/")


def api_call(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> Any:
    """Call the Authentik API and return decoded JSON when present."""
    url = _authentik_api_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    token = get_env("AUTHENTIK_BOOTSTRAP_TOKEN", required=True)
    request = urllib.request.Request(
        url,
        method=method,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in expected:
                raise SystemExit(
                    f"{method} {url} returned unexpected status {response.status}"
                )
            content = response.read().decode("utf-8").strip()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as err:
        body_text = err.read().decode("utf-8", errors="replace")
        if err.code not in expected:
            raise SystemExit(f"{method} {url} failed: {err.code} {body_text}") from err
        return json.loads(body_text) if body_text else None
    except urllib.error.URLError as err:
        raise SystemExit(f"{method} {url} failed: {err.reason}") from err


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


def response_results(response: Any) -> list[dict[str, Any]]:
    """Normalize Authentik list responses used by supported installations."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        results = response.get("results", [])
        return results if isinstance(results, list) else []
    return []


def first_result(path: str, *, query: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first result from a paginated list endpoint."""
    results = response_results(api_call("GET", path, query=query))
    return results[0] if results else None


def resource_pk(resource: dict[str, Any]) -> Any:
    """Return a resource identifier across known Authentik response shapes."""
    for key in ("pk", "flow_uuid", "id"):
        if resource.get(key) is not None:
            return resource[key]
    raise SystemExit(f"Authentik resource response has no pk/id: {sorted(resource)}")


def resolve_flow_uuid(designation: str, slug: str, *, purpose: str) -> str:
    """Resolve an exact flow slug and validate its designation."""
    response = api_call(
        "GET",
        "/flows/instances/",
        query={"designation": designation, "page_size": 100},
    )
    flows = response_results(response)
    for flow in flows:
        if flow.get("slug") == slug:
            return str(resource_pk(flow))
    available = ", ".join(sorted(str(flow.get("slug")) for flow in flows)) or "none"
    raise SystemExit(
        f"{purpose} '{slug}' was not found with designation={designation}; "
        f"available matching-designation flows: {available}"
    )


def ensure_flow_uuid(designation: str, preferred_slugs: list[str]) -> str:
    """Find a flow UUID by designation, preferring known default slugs."""
    response = api_call(
        "GET",
        "/flows/instances/",
        query={"designation": designation, "page_size": 100},
    )
    flows = response_results(response)
    if not flows:
        raise SystemExit(f"No flows found for designation={designation}")
    for slug in preferred_slugs:
        for flow in flows:
            if flow.get("slug") == slug:
                return str(resource_pk(flow))
    return str(resource_pk(flows[0]))


def ensure_google_source(
    config: GoogleSourceConfig,
    *,
    authentication_flow: str,
    enrollment_flow: str,
) -> tuple[dict[str, Any], str]:
    """Create or reconcile the upstream Google OAuth source by unique slug."""
    payload: dict[str, Any] = {
        "name": config.name,
        "slug": config.slug,
        "provider_type": "google",
        "authentication_flow": authentication_flow,
        "enrollment_flow": enrollment_flow,
        "user_matching_mode": "email_link",
        "enabled": True,
        "promoted": True,
        "additional_scopes": "openid email profile",
        "authorization_code_auth_method": "post_body",
        "oidc_well_known_url": GOOGLE_WELL_KNOWN_URL,
    }
    if config.client_id and config.client_secret:
        payload.update(
            consumer_key=config.client_id,
            consumer_secret=config.client_secret,
        )
    existing = first_result(
        "/sources/oauth/",
        query={"slug": config.slug, "page_size": 1},
    )
    if existing:
        source = api_call(
            "PATCH",
            f"/sources/oauth/{urllib.parse.quote(config.slug, safe='')}/",
            payload=payload,
            expected=(200,),
        )
        return source, "updated"
    if not config.client_id or not config.client_secret:
        raise SystemExit(
            "Cannot create the Authentik Google source without "
            "AUTHENTIK_GOOGLE_CLIENT_ID and AUTHENTIK_GOOGLE_CLIENT_SECRET"
        )
    source = api_call(
        "POST",
        "/sources/oauth/",
        payload=payload,
        expected=(201,),
    )
    return source, "created"


def find_identification_stage(login_flow_slug: str) -> dict[str, Any]:
    """Find the Identification stage actually bound to the production login flow."""
    flow = first_result(
        "/flows/instances/",
        query={
            "designation": "authentication",
            "slug": login_flow_slug,
            "page_size": 100,
        },
    )
    if not flow or flow.get("slug") != login_flow_slug:
        raise SystemExit(
            f"Authentication flow '{login_flow_slug}' was not found; cannot bind Google"
        )
    flow_stage_ids = {str(value) for value in flow.get("stages", [])}
    stages = response_results(
        api_call("GET", "/stages/identification/", query={"page_size": 100})
    )
    matches = []
    for stage in stages:
        stage_id = str(resource_pk(stage))
        flow_slugs = {
            flow_ref.get("slug")
            for flow_ref in stage.get("flow_set", [])
            if isinstance(flow_ref, dict)
        }
        if stage_id in flow_stage_ids or login_flow_slug in flow_slugs:
            matches.append(stage)
    if not matches:
        raise SystemExit(
            f"Authentication flow '{login_flow_slug}' has no Identification stage"
        )
    if len(matches) > 1:
        names = ", ".join(str(stage.get("name")) for stage in matches)
        raise SystemExit(
            f"Authentication flow '{login_flow_slug}' has multiple Identification "
            f"stages ({names}); refusing to guess"
        )
    return matches[0]


def _source_reference(value: Any) -> Any:
    """Normalize source UUID representations while preserving their order."""
    return resource_pk(value) if isinstance(value, dict) else value


def ensure_source_bound_to_identification_stage(
    stage: dict[str, Any],
    source_pk: str,
) -> tuple[dict[str, Any], str]:
    """Append Google to an Identification stage without changing other fields."""
    sources = [_source_reference(value) for value in (stage.get("sources") or [])]
    if source_pk in sources:
        return stage, "already_attached"
    sources.append(source_pk)
    stage_pk = resource_pk(stage)
    updated = api_call(
        "PATCH",
        f"/stages/identification/{stage_pk}/",
        payload={"sources": sources},
        expected=(200,),
    )
    return updated, "attached"


def bootstrap_google_federation(config: GoogleSourceConfig) -> dict[str, Any]:
    """Reconcile the Google source and its production Identification-stage binding."""
    authentication_flow = resolve_flow_uuid(
        "authentication",
        config.authentication_flow_slug,
        purpose="Google authentication flow",
    )
    enrollment_flow = resolve_flow_uuid(
        "enrollment",
        config.enrollment_flow_slug,
        purpose="Google enrollment flow",
    )
    source, source_status = ensure_google_source(
        config,
        authentication_flow=authentication_flow,
        enrollment_flow=enrollment_flow,
    )
    source_id = str(resource_pk(source))
    stage = find_identification_stage(config.login_flow_slug)
    bound_stage, binding_status = ensure_source_bound_to_identification_stage(
        stage,
        source_id,
    )
    return {
        "google_source_slug": config.slug,
        "google_source_pk": source_id,
        "google_source_status": source_status,
        "identification_stage": bound_stage.get("name") or stage.get("name"),
        "identification_stage_pk": str(resource_pk(bound_stage)),
        "binding_status": binding_status,
        "credential_source": config.credential_source,
        "callback_path": f"/source/oauth/callback/{config.slug}/",
    }


def ensure_signing_key() -> str:
    """Return the default certificate key pair used to sign OIDC tokens."""
    response = api_call(
        "GET",
        "/crypto/certificatekeypairs/",
        query={"page_size": 100},
    )
    certificates = response_results(response)
    if not certificates:
        raise SystemExit("No certificate key pairs found for OIDC signing")
    for certificate in certificates:
        if certificate.get("private_key_available"):
            return str(resource_pk(certificate))
    raise SystemExit("No certificate key pair with an available private key found")


def ensure_scope_mappings(scope_names: list[str]) -> list[str]:
    """Return the property mapping PKs for the requested OIDC scopes."""
    response = api_call(
        "GET",
        "/propertymappings/provider/scope/",
        query={"page_size": 100},
    )
    mappings = response_results(response)
    by_scope = {
        mapping.get("scope_name"): str(resource_pk(mapping)) for mapping in mappings
    }
    missing = [scope for scope in scope_names if scope not in by_scope]
    if missing:
        raise SystemExit(f"Missing Authentik scope mappings for: {', '.join(missing)}")
    return [by_scope[scope] for scope in scope_names]


def ensure_provider(
    config: OIDCApplicationConfig,
    authorization_flow: str,
    invalidation_flow: str,
    *,
    signing_key: str,
    property_mappings: list[str],
) -> tuple[dict[str, Any], str]:
    """Create or update one dedicated OAuth2 provider."""
    redirect_uris = []
    for entry in config.redirect_uris:
        matching_mode = "strict"
        url = entry
        if entry.startswith("regex|"):
            matching_mode = "regex"
            url = entry.split("|", 1)[1]
        elif entry.startswith("strict|"):
            url = entry.split("|", 1)[1]
        redirect_uris.append({"matching_mode": matching_mode, "url": url})
    payload = {
        "name": config.provider_name,
        "authorization_flow": authorization_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
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
        query={"name": config.provider_name, "page_size": 1},
    )
    if existing:
        provider_id = resource_pk(existing)
        provider = api_call(
            "PATCH",
            f"/providers/oauth2/{provider_id}/",
            payload=payload,
            expected=(200,),
        )
        return provider, "updated"
    provider = api_call(
        "POST", "/providers/oauth2/", payload=payload, expected=(201,)
    )
    return provider, "created"


def ensure_application(
    config: OIDCApplicationConfig, provider_id: int
) -> tuple[dict[str, Any], str]:
    """Create or update an application bound to its dedicated provider."""
    payload = {
        "name": config.app_name,
        "slug": config.app_slug,
        "provider": provider_id,
        "meta_launch_url": config.meta_launch_url,
        "open_in_new_tab": True,
        "policy_engine_mode": config.policy_engine_mode,
    }
    existing = first_result(
        "/core/applications/",
        query={"slug": config.app_slug, "page_size": 1},
    )
    if existing:
        application = api_call(
            "PATCH",
            f"/core/applications/{existing['slug']}/",
            payload=payload,
            expected=(200,),
        )
        return application, "updated"
    application = api_call(
        "POST", "/core/applications/", payload=payload, expected=(201,)
    )
    return application, "created"


def ensure_oidc_application(
    config: OIDCApplicationConfig,
    authorization_flow: str,
    invalidation_flow: str,
    *,
    signing_key: str,
    property_mappings: list[str],
) -> dict[str, Any]:
    """Reconcile a dedicated OIDC provider/application pair."""
    provider, provider_status = ensure_provider(
        config,
        authorization_flow,
        invalidation_flow,
        signing_key=signing_key,
        property_mappings=property_mappings,
    )
    provider_id = resource_pk(provider)
    application, application_status = ensure_application(config, provider_id)
    return {
        "provider_id": provider_id,
        "application_slug": application["slug"],
        "provider_status": provider_status,
        "application_status": application_status,
    }


def ensure_user(config: OIDCClientConfig) -> dict[str, Any]:
    """Create or update the existing local break-glass Authentik user."""
    payload = {
        "username": config.user_email,
        "name": config.user_name,
        "email": config.user_email,
        "is_active": True,
        "attributes": {},
    }
    existing = first_result(
        "/core/users/",
        query={"email": config.user_email, "page_size": 1},
    )
    if existing:
        user_id = resource_pk(existing)
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
        f"/core/users/{resource_pk(user)}/set_password/",
        payload={"password": config.user_password},
        expected=(204,),
    )
    return user


def bootstrap_oidc_client(config: OIDCClientConfig) -> dict[str, Any]:
    """Run the original GPT OIDC provider/application/local-user bootstrap."""
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
    provider, _provider_status = ensure_provider(
        config,
        authorization_flow,
        invalidation_flow,
        signing_key=signing_key,
        property_mappings=property_mappings,
    )
    provider_id = resource_pk(provider)
    application, _application_status = ensure_application(config, provider_id)
    user = ensure_user(config)
    setup_urls = api_call(
        "GET",
        f"/providers/oauth2/{provider_id}/setup_urls/",
        expected=(200,),
    )
    return {
        "provider_id": provider_id,
        "application_slug": application["slug"],
        "user_email": user["email"],
        "setup_urls": setup_urls,
    }


def bootstrap_grafana_sso(config: OIDCApplicationConfig) -> dict[str, Any]:
    """Reconcile the dedicated Grafana OIDC provider/application pair."""
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
    return ensure_oidc_application(
        config,
        authorization_flow,
        invalidation_flow,
        signing_key=ensure_signing_key(),
        property_mappings=ensure_scope_mappings(["openid", "email", "profile"]),
    )


def print_bootstrap_result(result: dict[str, Any]) -> None:
    """Print a secret-free, machine-readable bootstrap summary."""
    print(json.dumps(result, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--google-only",
        action="store_true",
        help="reconcile only upstream Google federation and its login-stage binding",
    )
    parser.add_argument(
        "--grafana-sso",
        action="store_true",
        help="also reconcile the dedicated Grafana OIDC provider and application",
    )
    return parser.parse_args()


def main() -> None:
    """Bootstrap Authentik after validating all required configuration."""
    args = parse_args()
    google_config = load_google_source_config()
    oidc_config = None if args.google_only else load_oidc_client_config()
    grafana_config = load_grafana_oidc_config() if args.grafana_sso else None
    get_env("AUTHENTIK_BOOTSTRAP_TOKEN", required=True)
    wait_for_api()
    result: dict[str, Any] = bootstrap_google_federation(google_config)
    if oidc_config:
        result["oidc_client"] = bootstrap_oidc_client(oidc_config)
    if grafana_config:
        result["grafana_sso"] = bootstrap_grafana_sso(grafana_config)
    print_bootstrap_result(result)


if __name__ == "__main__":
    main()
