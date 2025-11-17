import pytest
from fastapi import HTTPException

import services.training_agent.main as main


def test_id_token_path_prefers_local_verification(monkeypatch):
    calls = {"id": False, "tokeninfo": False}

    def fake_verify(token, request_obj, audience):
        calls["id"] = True
        assert token == "idtoken"
        assert audience == "client-id"
        return {"sub": "123"}

    def fake_get(url, params=None, timeout=None):
        calls["tokeninfo"] = True
        pytest.fail("tokeninfo should not be called for valid ID tokens")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    claims = main.verify_google_bearer("idtoken", "client-id")
    assert calls["id"] is True
    assert calls["tokeninfo"] is False
    assert claims["_token_type"] == "id_token"
    assert claims["sub"] == "123"


def test_access_token_path_uses_tokeninfo(monkeypatch):
    calls = {"tokeninfo": False}

    def fake_verify(token, request_obj, audience):
        raise ValueError("not an ID token")

    class DummyResponse:
        status_code = 200
        text = '{"aud": "client-id", "sub": "456"}'

        def json(self):
            return {"aud": "client-id", "sub": "456"}

    def fake_get(url, params=None, timeout=None):
        calls["tokeninfo"] = True
        assert params == {"access_token": "accesstoken"}
        assert timeout == 5
        return DummyResponse()

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    claims = main.verify_google_bearer("accesstoken", "client-id")
    assert calls["tokeninfo"] is True
    assert claims["_token_type"] == "access_token"
    assert claims["sub"] == "456"


def test_access_token_audience_mismatch(monkeypatch):
    def fake_verify(token, request_obj, audience):
        raise ValueError("not an ID token")

    class DummyResponse:
        status_code = 200
        text = '{"aud": "other-client"}'

        def json(self):
            return {"aud": "other-client"}

    def fake_get(url, params=None, timeout=None):
        return DummyResponse()

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")

    assert excinfo.value.status_code == 401
    assert "Invalid Google token" in excinfo.value.detail


def test_access_token_tokeninfo_failure_status(monkeypatch):
    def fake_verify(token, request_obj, audience):
        raise ValueError("not an ID token")

    class DummyResponse:
        status_code = 400
        text = "bad token"

        def json(self):
            return {}

    def fake_get(url, params=None, timeout=None):
        return DummyResponse()

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")
    assert excinfo.value.status_code == 401


def test_access_token_tokeninfo_raises(monkeypatch):
    def fake_verify(token, request_obj, audience):
        raise ValueError("not an ID token")

    def fake_get(url, params=None, timeout=None):
        raise RuntimeError("network issue")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")
    assert excinfo.value.status_code == 401


def test_require_google_auth_success(monkeypatch):
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    def fake_verify(token, audience):
        assert token == "goodtoken"
        assert audience == "client-id"
        return {"sub": "abc123"}

    monkeypatch.setattr(main, "verify_google_bearer", fake_verify)
    claims = main.require_google_auth(authorization="Bearer goodtoken")
    assert claims["sub"] == "abc123"


@pytest.mark.parametrize("header", [None, "", "Token xyz", "Bearer"])
def test_require_google_auth_missing_or_bad_header(monkeypatch, header):
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization=header)
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_empty_token(monkeypatch):
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer   ")
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_missing_client_id(monkeypatch):
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", None)
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer sometoken")
    assert excinfo.value.status_code == 500
    assert "missing RUNTRAINER_GOOGLE_CLIENT_ID" in excinfo.value.detail
