"""Unit tests for encryption helpers and the app JWT trust boundary."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import get_settings
from app.services.providers import ProviderTokenDetails, save_user_provider_token
from app.utils.security import (
    InvalidAppToken,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decrypt_token,
    encrypt_token,
)
from app.models.provider import UserProviderToken


settings = get_settings()


class FakeQuery:
    """Tiny query stub for provider token tests."""

    def __init__(self, items):
        self.items = items

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class FakeSession:
    """Minimal session stub to exercise save_user_provider_token."""

    def __init__(self):
        self.items = []

    def query(self, _model):
        return FakeQuery(self.items)

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def test_encrypt_roundtrip():
    """Encrypting and decrypting a token should round-trip."""
    raw = "secret"
    enc = encrypt_token(raw)
    assert enc != raw.encode()
    dec = decrypt_token(enc)
    assert dec == raw


def _encode_claims(claims):
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _claims(*, purpose="access", user_id=None, jti=None, issued_at=None):
    now = issued_at or datetime.now(timezone.utc)
    audience = (
        settings.jwt_access_audience
        if purpose == "access"
        else settings.jwt_refresh_audience
    )
    lifetime = (
        timedelta(minutes=settings.access_token_exp_minutes)
        if purpose == "access"
        else timedelta(days=settings.refresh_token_exp_days)
    )
    return {
        "sub": str(user_id or uuid.uuid4()),
        "exp": int((now + lifetime).timestamp()),
        "iat": int(now.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": audience,
        "jti": str(jti or uuid.uuid4()),
        "typ": purpose,
    }


def test_app_tokens_have_explicit_distinct_contracts_and_unique_ids():
    """Every app credential carries a complete purpose-specific boundary."""
    user_id = uuid.uuid4()
    access_tokens = [create_access_token(user_id) for _ in range(2)]
    refresh_tokens = [create_refresh_token(user_id) for _ in range(2)]
    access_claims = [decode_access_token(token) for token in access_tokens]
    refresh_claims = [decode_refresh_token(token) for token in refresh_tokens]

    for claims in access_claims:
        assert claims["sub"] == str(user_id)
        assert claims["typ"] == "access"
        assert claims["iss"] == settings.jwt_issuer
        assert claims["aud"] == settings.jwt_access_audience
        uuid.UUID(claims["jti"])
        assert claims["exp"] - claims["iat"] == settings.access_token_exp_minutes * 60
    for claims in refresh_claims:
        assert claims["sub"] == str(user_id)
        assert claims["typ"] == "refresh"
        assert claims["iss"] == settings.jwt_issuer
        assert claims["aud"] == settings.jwt_refresh_audience
        uuid.UUID(claims["jti"])
        assert claims["exp"] - claims["iat"] == settings.refresh_token_exp_days * 86400

    assert len({claims["jti"] for claims in access_claims + refresh_claims}) == 4


def test_access_and_refresh_tokens_cannot_cross_purpose_boundaries():
    user_id = uuid.uuid4()
    with pytest.raises(InvalidAppToken):
        decode_access_token(create_refresh_token(user_id))
    with pytest.raises(InvalidAppToken):
        decode_refresh_token(create_access_token(user_id))


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("typ", "refresh"),
        ("iss", "https://attacker.invalid"),
        ("aud", "fitness-pals-refresh"),
        ("sub", "not-a-uuid"),
        ("jti", "not-a-uuid"),
    ],
)
def test_access_decoder_rejects_wrong_boundary_claims(claim, value):
    claims = _claims()
    claims[claim] = value
    with pytest.raises(InvalidAppToken):
        decode_access_token(_encode_claims(claims))


@pytest.mark.parametrize("claim", ["typ", "iss", "aud", "sub", "jti", "iat", "exp"])
def test_access_decoder_rejects_missing_required_claims(claim):
    claims = _claims()
    del claims[claim]
    with pytest.raises(InvalidAppToken):
        decode_access_token(_encode_claims(claims))


@pytest.mark.parametrize(
    ("purpose", "decoder"),
    [("access", decode_access_token), ("refresh", decode_refresh_token)],
)
def test_app_decoder_rejects_expired_tokens(purpose, decoder):
    issued_at = datetime.now(timezone.utc) - timedelta(days=60)
    with pytest.raises(InvalidAppToken):
        decoder(_encode_claims(_claims(purpose=purpose, issued_at=issued_at)))


def test_save_user_provider_token_with_tenant():
    """Provider token save should persist tenant scoping and encrypt secrets."""
    db = FakeSession()
    tenant_id = uuid.uuid4()
    token = save_user_provider_token(
        db,
        ProviderTokenDetails(
            user_id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider="garmin",
            access_token="secret-token",
            refresh_token="refresh-token",
        ),
    )
    assert isinstance(token, UserProviderToken)
    assert token.tenant_id == tenant_id
    assert token.access_token_encrypted != b"secret-token"
    assert token.refresh_token_encrypted != b"refresh-token"


def test_save_user_provider_token_requires_access_token():
    """Provider token save should reject missing access token."""
    db = FakeSession()
    try:
        save_user_provider_token(
            db,
            ProviderTokenDetails(
                user_id=uuid.uuid4(),
                provider="garmin",
                access_token="",
            ),
        )
    except ValueError:
        return
    raise AssertionError("Expected ValueError for missing access_token")
