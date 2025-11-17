import uuid
from datetime import timedelta

from app.utils.security import encrypt_token, decrypt_token, create_jwt_token
from app.config import get_settings


def test_encrypt_roundtrip():
    raw = "secret"
    enc = encrypt_token(raw)
    assert enc != raw.encode()
    dec = decrypt_token(enc)
    assert dec == raw


def test_jwt_creation():
    token = create_jwt_token(str(uuid.uuid4()), timedelta(minutes=5))
    assert token
