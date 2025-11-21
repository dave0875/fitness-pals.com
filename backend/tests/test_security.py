"""Unit tests for symmetric encryption helpers and JWT creation."""

import uuid
from datetime import timedelta

from app.utils.security import encrypt_token, decrypt_token, create_jwt_token


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
