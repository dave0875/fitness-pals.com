"""Unit tests for symmetric encryption helpers and JWT creation."""

import uuid
from datetime import timedelta

from app.services.providers import ProviderTokenDetails, save_user_provider_token
from app.utils.security import encrypt_token, decrypt_token, create_jwt_token
from app.models.provider import UserProviderToken


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


def test_jwt_creation():
    """JWT helper should emit a signed token."""
    token = create_jwt_token(str(uuid.uuid4()), timedelta(minutes=5))
    assert token


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
