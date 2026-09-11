"""Configuration parsing regression tests."""

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
