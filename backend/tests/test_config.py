"""Configuration parsing regression tests."""

import pytest

from app.config import Settings


def make_settings(**overrides):
    values = {
        "jwt_secret": "test-jwt-secret",
        "database_url": "sqlite:///test.db",
        "fernet_key": "test-fernet-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_empty_optional_oauth_urls_normalize_to_none():
    settings = make_settings(
        google_redirect_uri="",
        oidc_issuer="",
        oidc_redirect_uri="",
        web_oidc_issuer="",
        web_oidc_redirect_uri="",
        microsoft_redirect_uri="",
        apple_redirect_uri="",
    )

    assert settings.google_redirect_uri is None
    assert settings.oidc_issuer is None
    assert settings.oidc_redirect_uri is None
    assert settings.web_oidc_issuer is None
    assert settings.web_oidc_redirect_uri is None
    assert settings.microsoft_redirect_uri is None
    assert settings.apple_redirect_uri is None


def test_configured_optional_oauth_url_remains_validated():
    settings = make_settings(web_oidc_issuer="https://auth.fitness-pals.com/application/o/web/")

    assert str(settings.web_oidc_issuer) == "https://auth.fitness-pals.com/application/o/web/"


def test_direct_google_fallback_is_disabled_by_default():
    settings = make_settings(
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="https://example.com/auth/google/callback",
    )

    assert settings.google_fallback_enabled is False


def test_access_and_refresh_audiences_must_be_distinct():
    with pytest.raises(ValueError, match="must be distinct"):
        make_settings(jwt_access_audience="same", jwt_refresh_audience="same")


@pytest.mark.parametrize(
    "field",
    ["jwt_issuer", "jwt_access_audience", "jwt_refresh_audience"],
)
def test_app_jwt_boundary_values_cannot_be_blank(field):
    with pytest.raises(ValueError, match="cannot be empty"):
        make_settings(**{field: "   "})
