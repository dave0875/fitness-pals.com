"""Tests for the reproducible Authentik Google federation bootstrap."""

from __future__ import annotations

import json
import textwrap
from types import SimpleNamespace

import pytest

from scripts import bootstrap_authentik as bootstrap


@pytest.fixture(autouse=True)
def google_credentials(monkeypatch):
    """Use dedicated, non-production Google credentials by default."""
    monkeypatch.setenv("AUTHENTIK_GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", raising=False)


def _google_config() -> bootstrap.GoogleSourceConfig:
    return bootstrap.load_google_source_config()


def _evaluate_authentik_expression(expression: str, **context):
    """Evaluate a trusted mapping expression in the shape Authentik supplies."""
    namespace = dict(context)
    exec("def evaluate_mapping():\n" + textwrap.indent(expression, "    "), namespace)
    return namespace["evaluate_mapping"]()


def test_google_source_is_created_when_absent(monkeypatch):
    """An absent Google source is created with verified 2026.2.1 fields."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": []}
        return {
            "pk": "source-uuid",
            "slug": "google",
            "name": "Google",
            "provider_type": "google",
        }

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    source, status = bootstrap.ensure_google_source(
        _google_config(),
        authentication_flow="authentication-flow-uuid",
        enrollment_flow="enrollment-flow-uuid",
        user_property_mapping_id="verified-email-map",
    )

    assert status == "created"
    assert source["pk"] == "source-uuid"
    assert [call[:2] for call in calls] == [
        ("GET", "/sources/oauth/"),
        ("POST", "/sources/oauth/"),
    ]
    payload = calls[-1][2]["payload"]
    assert payload == {
        "name": "Google",
        "slug": "google",
        "provider_type": "google",
        "consumer_key": "test-google-client-id",
        "consumer_secret": "test-google-client-secret",
        "authentication_flow": "authentication-flow-uuid",
        "enrollment_flow": "enrollment-flow-uuid",
        "user_property_mappings": ["verified-email-map"],
        "user_matching_mode": "email_link",
        "enabled": True,
        "promoted": True,
        "additional_scopes": "openid email profile",
        "authorization_code_auth_method": "post_body",
        "oidc_well_known_url": "https://accounts.google.com/.well-known/openid-configuration",
    }


def test_google_source_mapping_preserves_upstream_email_verification(monkeypatch):
    """The source mapping stores verified status and the exact verified address."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": []}
        return {"pk": "source-map-uuid", **kwargs["payload"]}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    mapping, status = bootstrap.ensure_google_verified_email_source_mapping()

    assert status == "created"
    assert mapping["pk"] == "source-map-uuid"
    assert [call[:2] for call in calls] == [
        ("GET", "/propertymappings/source/oauth/"),
        ("POST", "/propertymappings/source/oauth/"),
    ]
    expression = calls[-1][2]["payload"]["expression"]
    assert 'info.get("email")' in expression
    assert "fitness_pals_google_email_verified" in expression
    assert "fitness_pals_google_verified_email" in expression
    assert _evaluate_authentik_expression(
        expression,
        info={"email": "  RUNNER@Example.COM ", "email_verified": True},
    ) == {
        "attributes": {
            "fitness_pals_google_email_verified": True,
            "fitness_pals_google_verified_email": "runner@example.com",
        }
    }
    assert _evaluate_authentik_expression(
        expression,
        info={"email": "runner@example.com", "email_verified": False},
    ) == {
        "attributes": {
            "fitness_pals_google_email_verified": False,
            "fitness_pals_google_verified_email": "",
        }
    }


@pytest.mark.parametrize(
    ("claims", "verified"),
    [
        ({"verified_email": True}, True),
        ({"email_verified": True}, True),
        ({"verified_email": False}, False),
        ({"verified_email": "true"}, False),
        ({"verified_email": 1}, False),
        ({}, False),
        ({"email_verified": False, "verified_email": True}, False),
        ({"email_verified": None, "verified_email": True}, False),
    ],
)
def test_google_profile_verification_reaches_web_claim(claims, verified):
    """Exercise both Google's built-in OAuth profile and OIDC claim shapes."""
    email = " Runner@Example.com "
    attributes = _evaluate_authentik_expression(
        bootstrap.GOOGLE_VERIFIED_EMAIL_SOURCE_MAPPING_EXPRESSION,
        info={"id": "google-subject", "email": email, **claims},
    )["attributes"]
    result = _evaluate_authentik_expression(
        bootstrap.VERIFIED_EMAIL_SCOPE_MAPPING_EXPRESSION,
        request=SimpleNamespace(user=SimpleNamespace(email=email, attributes=attributes)),
    )
    assert result == {"email": email, "email_verified": verified}
    assert attributes["fitness_pals_google_verified_email"] == (
        "runner@example.com" if verified else ""
    )


def test_source_authentication_saves_returning_user_before_login(monkeypatch):
    """Default source auth only logs in; mapped attributes need a write stage."""
    calls = []
    bindings = [{"pk": "login-binding", "stage": "login", "order": 0}]
    stages = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": stages if path == "/stages/user_write/" else bindings}
        if path == "/stages/user_write/":
            assert kwargs["payload"]["user_creation_mode"] == "never_create"
            stages.append({"pk": "write", **kwargs["payload"]})
            return stages[-1]
        if path == "/flows/bindings/":
            assert kwargs["payload"]["target"] == "source-auth-flow"
            assert kwargs["payload"]["stage"] == "write"
            assert kwargs["payload"]["order"] < 0
            bindings.append({"pk": "write-binding", **kwargs["payload"]})
            return bindings[-1]
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    assert bootstrap.ensure_source_authentication_user_write("source-auth-flow") == "created"
    assert bindings[0] == {"pk": "login-binding", "stage": "login", "order": 0}
    calls.clear()
    assert bootstrap.ensure_source_authentication_user_write("source-auth-flow") == "already_configured"
    assert all(method == "GET" for method, _, _ in calls)


def test_source_authentication_repairs_unsafe_write_mode_and_order(monkeypatch):
    """Reconciliation restores update-only writes ahead of existing stages."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path == "/stages/user_write/":
            return {"results": [{"pk": "write", "user_creation_mode": "always_create"}]}
        if method == "GET" and path == "/flows/bindings/":
            return {"results": [
                {"pk": "write-binding", "stage": "write", "order": 10},
                {"pk": "login-binding", "stage": "login", "order": 0},
            ]}
        return kwargs["payload"]

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    assert bootstrap.ensure_source_authentication_user_write("source-auth-flow") == "updated"
    mutations = [(path, kwargs["payload"]) for method, path, kwargs in calls if method != "GET"]
    assert mutations == [
        ("/stages/user_write/write/", {"user_creation_mode": "never_create"}),
        ("/flows/bindings/write-binding/", {"order": -1}),
    ]


def test_verified_email_scope_mapping_emits_claim_only_for_current_verified_email(
    monkeypatch,
):
    """The web scope only claims verification while the source email still matches."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": []}
        return {"pk": "scope-map-uuid", **kwargs["payload"]}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    mapping, status = bootstrap.ensure_verified_email_scope_mapping()

    assert status == "created"
    assert mapping["pk"] == "scope-map-uuid"
    assert [call[:2] for call in calls] == [
        ("GET", "/propertymappings/provider/scope/"),
        ("POST", "/propertymappings/provider/scope/"),
    ]
    payload = calls[-1][2]["payload"]
    assert payload["scope_name"] == "email"
    expression = payload["expression"]
    assert "fitness_pals_google_email_verified" in expression
    assert "fitness_pals_google_verified_email" in expression
    assert '"email_verified"' in expression
    assert "email.strip().casefold()" in expression
    verified_user = SimpleNamespace(
        email=" Runner@Example.com ",
        attributes={
            "fitness_pals_google_email_verified": True,
            "fitness_pals_google_verified_email": "runner@example.com",
        },
    )
    assert _evaluate_authentik_expression(
        expression,
        request=SimpleNamespace(user=verified_user),
    ) == {"email": " Runner@Example.com ", "email_verified": True}
    verified_user.email = "attacker@example.com"
    assert _evaluate_authentik_expression(
        expression,
        request=SimpleNamespace(user=verified_user),
    ) == {"email": "attacker@example.com", "email_verified": False}


def test_web_provider_uses_custom_email_scope_and_preserves_other_scopes(monkeypatch):
    """The website provider replaces only its default email scope mapping."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/core/applications/fitness-pals-web/":
            return {"slug": "fitness-pals-web", "provider": 42}
        if path == "/providers/oauth2/42/":
            if method == "GET":
                return {
                    "pk": 42,
                    "property_mappings": [
                        "openid-map",
                        "default-email-map",
                        "profile-map",
                    ],
                }
            return {
                "pk": 42,
                "property_mappings": kwargs["payload"]["property_mappings"],
            }
        if path == "/propertymappings/provider/scope/":
            return {
                "results": [
                    {"pk": "openid-map", "scope_name": "openid"},
                    {"pk": "default-email-map", "scope_name": "email"},
                    {"pk": "verified-email-map", "scope_name": "email"},
                    {"pk": "profile-map", "scope_name": "profile"},
                ]
            }
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    result = bootstrap.ensure_web_verified_email_scope_mapping(
        "https://auth.example.com/application/o/fitness-pals-web/",
        "verified-email-map",
    )

    assert result == {
        "application_slug": "fitness-pals-web",
        "provider_id": 42,
        "status": "updated",
    }
    assert [call[:2] for call in calls] == [
        ("GET", "/core/applications/fitness-pals-web/"),
        ("GET", "/providers/oauth2/42/"),
        ("GET", "/propertymappings/provider/scope/"),
        ("PATCH", "/providers/oauth2/42/"),
    ]
    assert calls[-1][2]["payload"] == {
        "property_mappings": ["openid-map", "profile-map", "verified-email-map"]
    }


def test_web_provider_mapping_requires_authentik_application_issuer_shape():
    """A malformed issuer is rejected rather than attaching a claim to a guessed app."""
    with pytest.raises(SystemExit, match="RUNTRAINER_WEB_OIDC_ISSUER.*application/o"):
        bootstrap.ensure_web_verified_email_scope_mapping(
            "https://auth.example.com/not-the-web-app/", "verified-email-map"
        )


def test_google_federation_bootstrap_wires_both_verified_email_mappings(monkeypatch):
    """Google source and website scope are reconciled in the regular bootstrap."""
    monkeypatch.setenv(
        "RUNTRAINER_WEB_OIDC_ISSUER",
        "https://auth.example.com/application/o/fitness-pals-web/",
    )
    source_calls = []
    write_flows = []
    monkeypatch.setattr(
        bootstrap, "ensure_source_authentication_user_write",
        lambda flow: write_flows.append(flow) or "created",
    )
    monkeypatch.setattr(
        bootstrap,
        "resolve_flow_uuid",
        lambda designation, slug, *, purpose: f"{designation}-flow",
    )
    monkeypatch.setattr(
        bootstrap,
        "ensure_google_verified_email_source_mapping",
        lambda: ({"pk": "source-mapping"}, "created"),
    )

    def fake_ensure_source(config, **kwargs):
        source_calls.append((config, kwargs))
        return {"pk": "google-source"}, "updated"

    monkeypatch.setattr(bootstrap, "ensure_google_source", fake_ensure_source)
    monkeypatch.setattr(
        bootstrap,
        "find_identification_stage",
        lambda _slug: {"pk": "stage", "name": "production-identification"},
    )
    monkeypatch.setattr(
        bootstrap,
        "ensure_source_bound_to_identification_stage",
        lambda stage, _source: (stage, "already_attached"),
    )
    monkeypatch.setattr(
        bootstrap,
        "ensure_verified_email_scope_mapping",
        lambda: ({"pk": "email-scope-mapping"}, "created"),
    )
    monkeypatch.setattr(
        bootstrap,
        "ensure_web_verified_email_scope_mapping",
        lambda issuer, mapping_id: {
            "application_slug": "fitness-pals-web",
            "provider_id": 42,
            "status": "updated",
        },
    )

    result = bootstrap.bootstrap_google_federation(_google_config())

    assert write_flows == ["authentication-flow"]
    assert result["google_authentication_user_write_status"] == "created"
    assert source_calls[0][1]["user_property_mapping_id"] == "source-mapping"
    assert result["google_verified_email_mapping_status"] == "created"
    assert result["web_email_scope_definition_status"] == "created"
    assert result["web_email_scope_mapping_status"] == "updated"
    assert result["web_oidc_application_slug"] == "fitness-pals-web"
    assert result["web_oidc_provider_id"] == 42


def test_existing_google_source_is_patched_not_duplicated(monkeypatch):
    """An existing slug is reconciled with PATCH, including credential rotation."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {
                "results": [
                    {
                        "pk": "source-uuid",
                        "slug": "google",
                        "user_property_mappings": ["existing-map"],
                    }
                ]
            }
        assert method == "PATCH"
        assert path == "/sources/oauth/google/"
        return {"pk": "source-uuid", "slug": "google", "enabled": True}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    source, status = bootstrap.ensure_google_source(
        _google_config(),
        authentication_flow="authentication-flow-uuid",
        enrollment_flow="enrollment-flow-uuid",
        user_property_mapping_id="verified-email-map",
    )

    assert status == "updated"
    assert source["pk"] == "source-uuid"
    assert [method for method, _, _ in calls] == ["GET", "PATCH"]
    assert calls[-1][2]["payload"]["consumer_secret"] == "test-google-client-secret"
    assert calls[-1][2]["payload"]["user_property_mappings"] == [
        "existing-map",
        "verified-email-map",
    ]


def test_identification_stage_preserves_sources_and_adds_google(monkeypatch):
    """Binding changes only the sources array and preserves existing sources."""
    calls = []
    stage = {
        "pk": "stage-uuid",
        "name": "production-identification",
        "sources": ["existing-source-uuid"],
        "user_fields": ["email", "username"],
    }

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {**stage, "sources": kwargs["payload"]["sources"]}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    updated, status = bootstrap.ensure_source_bound_to_identification_stage(
        stage, "google-source-uuid"
    )

    assert status == "attached"
    assert updated["sources"] == ["existing-source-uuid", "google-source-uuid"]
    assert calls == [
        (
            "PATCH",
            "/stages/identification/stage-uuid/",
            {
                "payload": {"sources": ["existing-source-uuid", "google-source-uuid"]},
                "expected": (200,),
            },
        )
    ]
    assert stage["user_fields"] == ["email", "username"]


def test_google_source_binding_is_not_duplicated(monkeypatch):
    """No stage update is made when Google is already attached."""
    stage = {
        "pk": "stage-uuid",
        "name": "production-identification",
        "sources": ["existing-source-uuid", "google-source-uuid"],
    }

    def unexpected_api_call(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(bootstrap, "api_call", unexpected_api_call)
    unchanged, status = bootstrap.ensure_source_bound_to_identification_stage(
        stage, "google-source-uuid"
    )

    assert unchanged is stage
    assert status == "already_attached"


def test_bootstrap_output_never_contains_secrets(capsys):
    """Structured output exposes resource state, not supplied credentials."""
    result = {
        "google_source_slug": "google",
        "google_source_pk": "source-uuid",
        "google_source_status": "updated",
        "identification_stage": "production-identification",
        "identification_stage_pk": "stage-uuid",
        "binding_status": "already_attached",
        "credential_source": "AUTHENTIK_GOOGLE_CLIENT_ID/AUTHENTIK_GOOGLE_CLIENT_SECRET",
        "callback_path": "/source/oauth/callback/google/",
    }

    bootstrap.print_bootstrap_result(result)
    output = capsys.readouterr().out

    assert json.loads(output) == result
    assert "test-google-client-id" not in output
    assert "test-google-client-secret" not in output


def test_missing_google_credentials_fail_clearly(monkeypatch):
    """Missing credentials are allowed for reconciling an existing source."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", raising=False)

    config = bootstrap.load_google_source_config()
    assert config.client_id is None
    assert config.client_secret is None
    assert "credentials retained" in config.credential_source

    monkeypatch.setenv("AUTHENTIK_GOOGLE_CLIENT_ID", "replace-me")
    monkeypatch.setenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", "replace-me")
    with pytest.raises(SystemExit, match="placeholder"):
        bootstrap.load_google_source_config()


def test_partial_dedicated_credentials_do_not_mix_pairs(monkeypatch):
    """A dedicated ID is never combined with the fallback client secret."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "fallback-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "fallback-secret")

    with pytest.raises(SystemExit, match="must be set together"):
        bootstrap.load_google_source_config()


def test_google_credentials_do_not_fall_back_to_direct_pair(monkeypatch):
    """Direct-app credentials never become Authentik upstream credentials."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID")
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "fallback-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "fallback-secret")

    config = bootstrap.load_google_source_config()
    assert config.client_id is None
    assert config.client_secret is None


def test_existing_google_source_is_reconciled_without_credentials(monkeypatch):
    """An existing source keeps its Authentik secret when no rotation pair exists."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", raising=False)
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": [{"pk": "source-uuid", "slug": "google"}]}
        return {"pk": "source-uuid", "slug": "google", "enabled": True}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    bootstrap.ensure_google_source(
        bootstrap.load_google_source_config(),
        authentication_flow="authentication-flow-uuid",
        enrollment_flow="enrollment-flow-uuid",
        user_property_mapping_id="verified-email-map",
    )

    assert "consumer_key" not in calls[-1][2]["payload"]
    assert "consumer_secret" not in calls[-1][2]["payload"]


def test_new_google_source_requires_dedicated_credentials(monkeypatch):
    """A missing source cannot be created without dedicated upstream credentials."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(bootstrap, "api_call", lambda *args, **kwargs: {"results": []})

    with pytest.raises(SystemExit, match="Cannot create.*AUTHENTIK_GOOGLE_CLIENT_ID"):
        bootstrap.ensure_google_source(
            bootstrap.load_google_source_config(),
            authentication_flow="authentication-flow-uuid",
            enrollment_flow="enrollment-flow-uuid",
            user_property_mapping_id="verified-email-map",
        )


def test_flow_lookup_failure_has_actionable_error(monkeypatch):
    """Missing source flows identify the requested slug and designation."""
    monkeypatch.setattr(
        bootstrap,
        "api_call",
        lambda *args, **kwargs: {
            "results": [{"pk": "other-uuid", "slug": "other-enrollment-flow"}]
        },
    )

    with pytest.raises(
        SystemExit,
        match="Google enrollment flow.*default-source-enrollment.*enrollment",
    ):
        bootstrap.resolve_flow_uuid(
            "enrollment",
            "default-source-enrollment",
            purpose="Google enrollment flow",
        )


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ({"pk": "uuid-from-pk"}, "uuid-from-pk"),
        ({"flow_uuid": "uuid-from-flow"}, "uuid-from-flow"),
        ({"id": 42}, 42),
    ],
)
def test_resource_pk_handles_authentik_response_shapes(resource, expected):
    """Known Authentik resource identifier variants are normalized."""
    assert bootstrap.resource_pk(resource) == expected


def test_identification_stage_is_discovered_from_production_flow(monkeypatch):
    """The stage is selected by the flow's stage UUIDs, not a guessed stage name."""
    responses = iter(
        [
            {
                "results": [
                    {
                        "pk": "login-flow-uuid",
                        "slug": "production-login-flow",
                        "designation": "authentication",
                        "stages": ["prompt-stage-uuid", "identification-stage-uuid"],
                    }
                ]
            },
            {
                "results": [
                    {
                        "pk": "other-identification-stage",
                        "name": "unused",
                        "sources": [],
                        "flow_set": [],
                    },
                    {
                        "pk": "identification-stage-uuid",
                        "name": "production-identification",
                        "sources": [],
                        "flow_set": [],
                    },
                ]
            },
        ]
    )
    monkeypatch.setattr(bootstrap, "api_call", lambda *args, **kwargs: next(responses))

    stage = bootstrap.find_identification_stage("production-login-flow")

    assert stage["pk"] == "identification-stage-uuid"
    assert stage["name"] == "production-identification"


def test_identification_stage_accepts_flow_set_response_variation(monkeypatch):
    """The 2026.2.1 flow_set representation is a safe discovery fallback."""
    responses = iter(
        [
            {
                "results": [
                    {
                        "pk": "login-flow-uuid",
                        "slug": "production-login-flow",
                        "designation": "authentication",
                    }
                ]
            },
            {
                "results": [
                    {
                        "pk": "identification-stage-uuid",
                        "name": "production-identification",
                        "sources": [],
                        "flow_set": [{"slug": "production-login-flow"}],
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(bootstrap, "api_call", lambda *args, **kwargs: next(responses))

    assert bootstrap.find_identification_stage("production-login-flow")["pk"] == (
        "identification-stage-uuid"
    )


def test_grafana_oidc_application_is_reconciled_with_least_privilege(monkeypatch):
    """Grafana SSO receives a dedicated confidential client and application."""
    monkeypatch.setenv("GRAFANA_OIDC_CLIENT_ID", "grafana-client")
    monkeypatch.setenv("GRAFANA_OIDC_CLIENT_SECRET", "grafana-secret")
    config = bootstrap.load_grafana_oidc_config()
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path in {
            "/providers/oauth2/",
            "/core/applications/",
        }:
            return {"results": []}
        if path == "/providers/oauth2/":
            return {"pk": 42, "name": "Grafana"}
        if path == "/core/applications/":
            return {"slug": "grafana", "name": "Grafana"}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    result = bootstrap.ensure_oidc_application(
        config,
        authorization_flow="authorization-flow",
        invalidation_flow="invalidation-flow",
        signing_key="signing-key",
        property_mappings=["openid-mapping", "email-mapping", "profile-mapping"],
    )

    assert result == {
        "provider_id": 42,
        "application_slug": "grafana",
        "provider_status": "created",
        "application_status": "created",
    }
    provider_payload = calls[1][2]["payload"]
    assert provider_payload["client_type"] == "confidential"
    assert provider_payload["client_id"] == "grafana-client"
    assert provider_payload["client_secret"] == "grafana-secret"
    assert provider_payload["redirect_uris"] == [
        {
            "matching_mode": "strict",
            "url": "https://grafana.fitness-pals.com/login/generic_oauth",
        }
    ]
    application_payload = calls[3][2]["payload"]
    assert application_payload["slug"] == "grafana"
    assert application_payload["policy_engine_mode"] == "all"


def test_grafana_oidc_credentials_are_required_as_a_pair(monkeypatch):
    """A partial Grafana client configuration cannot reach Authentik."""
    monkeypatch.setenv("GRAFANA_OIDC_CLIENT_ID", "grafana-client")
    monkeypatch.delenv("GRAFANA_OIDC_CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit, match="must be set together"):
        bootstrap.load_grafana_oidc_config()


def test_grafana_oidc_credentials_cannot_both_be_absent(monkeypatch):
    """Compose inspection may omit credentials, but bootstrap must fail closed."""
    monkeypatch.delenv("GRAFANA_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAFANA_OIDC_CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit, match="Missing Grafana OIDC credentials"):
        bootstrap.load_grafana_oidc_config()
