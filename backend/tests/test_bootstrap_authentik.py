"""Tests for the reproducible Authentik Google federation bootstrap."""

from __future__ import annotations

import json

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
        "user_matching_mode": "email_link",
        "enabled": True,
        "promoted": True,
        "additional_scopes": "openid email profile",
        "authorization_code_auth_method": "post_body",
        "oidc_well_known_url": "https://accounts.google.com/.well-known/openid-configuration",
    }


def test_existing_google_source_is_patched_not_duplicated(monkeypatch):
    """An existing slug is reconciled with PATCH, including credential rotation."""
    calls = []

    def fake_api_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": [{"pk": "source-uuid", "slug": "google"}]}
        assert method == "PATCH"
        assert path == "/sources/oauth/google/"
        return {"pk": "source-uuid", "slug": "google", "enabled": True}

    monkeypatch.setattr(bootstrap, "api_call", fake_api_call)
    source, status = bootstrap.ensure_google_source(
        _google_config(),
        authentication_flow="authentication-flow-uuid",
        enrollment_flow="enrollment-flow-uuid",
    )

    assert status == "updated"
    assert source["pk"] == "source-uuid"
    assert [method for method, _, _ in calls] == ["GET", "PATCH"]
    assert calls[-1][2]["payload"]["consumer_secret"] == "test-google-client-secret"


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
    """Neither missing nor placeholder credentials can reach the Authentik API."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit, match="AUTHENTIK_GOOGLE_CLIENT_ID.*RUNTRAINER_GOOGLE_CLIENT_ID"):
        bootstrap.load_google_source_config()

    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "replace-me")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "replace-me")
    with pytest.raises(SystemExit, match="placeholder"):
        bootstrap.load_google_source_config()


def test_partial_dedicated_credentials_do_not_mix_pairs(monkeypatch):
    """A dedicated ID is never combined with the fallback client secret."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "fallback-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "fallback-secret")

    with pytest.raises(SystemExit, match="must be set together"):
        bootstrap.load_google_source_config()


def test_google_credentials_deliberately_fall_back_to_direct_pair(monkeypatch):
    """The documented emergency-fallback OAuth pair may bootstrap Authentik."""
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_ID")
    monkeypatch.delenv("AUTHENTIK_GOOGLE_CLIENT_SECRET")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "fallback-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "fallback-secret")

    config = bootstrap.load_google_source_config()

    assert config.client_id == "fallback-id"
    assert config.client_secret == "fallback-secret"
    assert config.credential_source.startswith("RUNTRAINER_GOOGLE_CLIENT_ID")


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
