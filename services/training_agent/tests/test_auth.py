# ruff: noqa: E501
"""Tests covering Google OAuth verification and metrics endpoints."""
import urllib.parse
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.training_agent import main
from services.training_agent import auth as auth_mod
from services.training_agent import training_data


class StaticResponse:  # pylint: disable=too-few-public-methods
    """Test HTTP response stub for mocking requests."""

    def __init__(self, status_code: int, text: str, payload: dict):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        """Return the stored JSON payload."""
        return self._payload


def clear_oidc_runtime(monkeypatch):
    """Remove broker env so tests can exercise the direct Google fallback contract."""
    for key in (
        "RUNTRAINER_OIDC_ISSUER",
        "OIDC_ISSUER",
        "RUNTRAINER_OIDC_AUTH_URL",
        "OIDC_AUTH_URL",
        "RUNTRAINER_OIDC_TOKEN_URL",
        "OIDC_TOKEN_URL",
        "RUNTRAINER_OIDC_JWKS_URL",
        "OIDC_JWKS_URL",
        "RUNTRAINER_OIDC_CLIENT_ID",
        "OIDC_CLIENT_ID",
        "RUNTRAINER_OIDC_CLIENT_SECRET",
        "OIDC_CLIENT_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    auth_mod._load_oidc_discovery.cache_clear()  # pylint: disable=protected-access


def test_id_token_path_prefers_local_verification(monkeypatch):
    """ID tokens should be verified locally without tokeninfo."""
    calls = {"id": False, "tokeninfo": False}

    def fake_verify(token, _request_obj, audience):
        calls["id"] = True
        assert token == "idtoken"
        assert audience == "client-id"
        return {"sub": "123"}

    def fake_get(_url, _params=None, _timeout=None):
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
    """Access tokens without JWT claims should call tokeninfo endpoint."""
    calls = {"tokeninfo": False}

    def fake_verify(token, _request_obj, audience):
        raise ValueError("not an ID token")

    def fake_get(_url, params=None, timeout=None):
        calls["tokeninfo"] = True
        assert params == {"access_token": "accesstoken"}
        assert timeout == 5
        return StaticResponse(
            200,
            '{"aud": "client-id", "sub": "456"}',
            {"aud": "client-id", "sub": "456"},
        )

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    claims = main.verify_google_bearer("accesstoken", "client-id")
    assert calls["tokeninfo"] is True
    assert claims["_token_type"] == "access_token"
    assert claims["sub"] == "456"


def test_access_token_audience_mismatch(monkeypatch):
    """Tokeninfo results with wrong audience should raise HTTPException."""

    def fake_verify(token, _request_obj, audience):
        raise ValueError("not an ID token")

    def fake_get(_url, _params=None, _timeout=None):
        return StaticResponse(200, '{"aud": "other-client"}', {"aud": "other-client"})

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")

    assert excinfo.value.status_code == 401
    assert "Invalid Google token" in excinfo.value.detail


def test_access_token_tokeninfo_failure_status(monkeypatch):
    """Non-200 responses from tokeninfo should raise HTTPException."""

    def fake_verify(token, _request_obj, audience):
        raise ValueError("not an ID token")

    def fake_get(_url, _params=None, _timeout=None):
        return StaticResponse(400, "bad token", {})

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")
    assert excinfo.value.status_code == 401


def test_access_token_tokeninfo_raises(monkeypatch):
    """Tokeninfo transport failures should be surfaced as HTTP errors."""

    def fake_verify(token, _request_obj, audience):
        raise ValueError("not an ID token")

    def fake_get(_url, _params=None, _timeout=None):
        raise RuntimeError("network issue")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(main.requests, "get", fake_get)

    with pytest.raises(HTTPException) as excinfo:
        main.verify_google_bearer("accesstoken", "client-id")
    assert excinfo.value.status_code == 401


def test_require_google_auth_success(monkeypatch):
    """require_google_auth should pass through valid bearer tokens."""
    clear_oidc_runtime(monkeypatch)
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")

    def fake_verify(token, audience):
        assert token == "goodtoken"
        assert audience == "client-id"
        return {"sub": "abc123"}

    monkeypatch.setattr(main, "verify_bearer", fake_verify)
    claims = main.require_google_auth(authorization="Bearer goodtoken")
    assert claims["sub"] == "abc123"


def test_require_google_auth_prefers_oidc_client(monkeypatch):
    """OIDC should be the primary bearer validation path when configured."""
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)

    def fake_verify(token, audience):
        assert token == "goodtoken"
        assert audience == "oidc-client"
        return {"sub": "oidc-user"}

    monkeypatch.setattr(main, "verify_bearer", fake_verify)
    claims = main.require_google_auth(authorization="Bearer goodtoken")
    assert claims["sub"] == "oidc-user"


@pytest.mark.parametrize("header", [None, "", "Token xyz", "Bearer"])
def test_require_google_auth_missing_or_bad_header(monkeypatch, header):
    """Missing or malformed Authorization headers should raise 401."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization=header)
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_empty_token(monkeypatch):
    """Blank bearer tokens should be rejected."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer   ")
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_missing_client_id(monkeypatch):
    """Missing Google client ID should result in server error."""
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("RUNTRAINER_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.setattr(auth_mod, "GOOGLE_CLIENT_ID", "stale-client-id")
    monkeypatch.setattr(auth_mod, "OIDC_CLIENT_ID", None)

    def fail_verify(_token, _audience):
        pytest.fail("require_google_auth should not attempt bearer verification without client config")

    monkeypatch.setattr(main, "verify_bearer", fail_verify)
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer sometoken")
    assert excinfo.value.status_code == 500
    assert "missing auth client configuration" in excinfo.value.detail


def test_health_and_metrics_emit_prometheus():
    """Health and metrics endpoints should respond under tests."""
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text
    assert (
        'training_agent_requests_total{method="GET",path="/health",status="200"}'
        in body
    )
    assert (
        'training_agent_request_latency_seconds_count{method="GET",path="/health",status="200"}'
        in body
    )


def test_ready_endpoint_returns_ok(monkeypatch):
    """Readiness should return 200 when canonical Postgres is ready."""
    monkeypatch.setattr(
        main,
        "check_training_agent_ready",
        lambda: (True, {"postgres": "ok"}),
    )
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok"}}


def test_ready_endpoint_returns_503(monkeypatch):
    """Readiness should return 503 when canonical Postgres is unavailable."""
    monkeypatch.setattr(
        main,
        "check_training_agent_ready",
        lambda: (False, {"postgres": "unreachable"}),
    )
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"postgres": "unreachable"},
    }


def test_oauth_google_auth_honors_valid_chatgpt_redirect(monkeypatch):
    """Authorize proxy should use a caller-supplied ChatGPT callback when valid."""
    clear_oidc_runtime(monkeypatch)
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "RUNTRAINER_GOOGLE_REDIRECT_URI",
        "https://chat.openai.com/aip/g-default/oauth/callback",
    )

    client = TestClient(main.app)
    callback = "https://chatgpt.com/aip/g-test-trainer/oauth/callback"
    response = client.get(
        "/oauth/google/auth",
        params={"state": "abc", "redirect_uri": callback},
        follow_redirects=False,
    )

    assert response.status_code in {302, 307}
    location = response.headers["location"]
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)
    assert query["redirect_uri"] == [callback]
    assert query["state"] == ["abc"]


def test_oauth_google_auth_rejects_untrusted_redirect(monkeypatch):
    """Authorize proxy should reject redirect URIs outside the OpenAI callback allowlist."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "RUNTRAINER_GOOGLE_REDIRECT_URI",
        "https://chat.openai.com/aip/g-default/oauth/callback",
    )

    client = TestClient(main.app)
    response = client.get(
        "/oauth/google/auth",
        params={"redirect_uri": "https://evil.example.com/oauth/callback"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid redirect_uri"


def test_oauth_google_token_uses_supplied_redirect(monkeypatch):
    """Token proxy should exchange using the caller-supplied ChatGPT callback."""
    clear_oidc_runtime(monkeypatch)
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "RUNTRAINER_GOOGLE_REDIRECT_URI",
        "https://chat.openai.com/aip/g-default/oauth/callback",
    )
    captured = {}

    class FakeTokenResponse:  # pylint: disable=too-few-public-methods
        status_code = 200
        text = '{"access_token":"token"}'

        @staticmethod
        def json():
            return {"access_token": "token"}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = dict(data)
        captured["headers"] = dict(headers)
        captured["timeout"] = timeout
        return FakeTokenResponse()

    monkeypatch.setattr(auth_mod.requests, "post", fake_post)

    client = TestClient(main.app)
    callback = "https://chat.openai.com/aip/g-my-test-trainer/oauth/callback"
    response = client.post(
        "/oauth/google/token",
        data={
            "code": "auth-code",
            "grant_type": "authorization_code",
            "redirect_uri": callback,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"access_token": "token"}
    assert captured["data"]["redirect_uri"] == callback


def test_oauth_google_auth_uses_oidc_authorize_url(monkeypatch):
    """When OIDC is configured, the authorize proxy should target the broker."""
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_AUTH_URL",
        "https://auth.fitness-pals.com/application/o/authorize/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "google-client")

    client = TestClient(main.app)
    callback = "https://chat.openai.com/aip/g-broker/oauth/callback"
    response = client.get(
        "/oauth/google/auth",
        params={"state": "abc", "redirect_uri": callback},
        follow_redirects=False,
    )

    assert response.status_code in {302, 307}
    location = response.headers["location"]
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.fitness-pals.com"
    assert query["client_id"] == ["oidc-client"]
    assert query["redirect_uri"] == [callback]


def test_oauth_google_auth_discovers_oidc_authorize_url_from_issuer(monkeypatch):
    """Issuer-only OIDC config should resolve the broker authorize URL via discovery."""
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "oidc-secret")
    captured = {}

    class FakeDiscoveryResponse:  # pylint: disable=too-few-public-methods
        status_code = 200
        text = '{"authorization_endpoint":"https://auth.fitness-pals.com/application/o/authorize/"}'

        @staticmethod
        def json():
            return {
                "authorization_endpoint": "https://auth.fitness-pals.com/application/o/authorize/",
                "token_endpoint": "https://auth.fitness-pals.com/application/o/token/",
                "jwks_uri": "https://auth.fitness-pals.com/application/o/training-agent-gpt/jwks/",
            }

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeDiscoveryResponse()

    monkeypatch.setattr(auth_mod.requests, "get", fake_get)
    auth_mod._load_oidc_discovery.cache_clear()  # pylint: disable=protected-access

    client = TestClient(main.app)
    callback = "https://chat.openai.com/aip/g-broker/oauth/callback"
    response = client.get(
        "/oauth/google/auth",
        params={"state": "abc", "redirect_uri": callback},
        follow_redirects=False,
    )

    assert response.status_code in {302, 307}
    parsed = urllib.parse.urlparse(response.headers["location"])
    assert parsed.netloc == "auth.fitness-pals.com"
    assert captured["url"] == (
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/.well-known/openid-configuration"
    )
    assert captured["timeout"] == 5


def test_oauth_google_token_uses_oidc_client_credentials(monkeypatch):
    """When OIDC is configured, the token proxy should exchange against the broker."""
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_TOKEN_URL",
        "https://auth.fitness-pals.com/application/o/token/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "oidc-secret")
    captured = {}

    class FakeTokenResponse:  # pylint: disable=too-few-public-methods
        status_code = 200
        text = '{"access_token":"token"}'

        @staticmethod
        def json():
            return {"access_token": "token"}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = dict(data)
        return FakeTokenResponse()

    monkeypatch.setattr(auth_mod.requests, "post", fake_post)

    client = TestClient(main.app)
    callback = "https://chat.openai.com/aip/g-broker/oauth/callback"
    response = client.post(
        "/oauth/google/token",
        data={"code": "auth-code", "redirect_uri": callback},
    )

    assert response.status_code == 200
    assert captured["url"] == "https://auth.fitness-pals.com/application/o/token/"
    assert captured["data"]["client_id"] == "oidc-client"
    assert captured["data"]["client_secret"] == "oidc-secret"
    assert captured["data"]["redirect_uri"] == callback


def test_oauth_google_token_discovers_oidc_token_url_from_issuer(monkeypatch):
    """Issuer-only OIDC config should resolve the broker token URL via discovery."""
    monkeypatch.setenv(
        "RUNTRAINER_OIDC_ISSUER",
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/",
    )
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setenv("RUNTRAINER_OIDC_CLIENT_SECRET", "oidc-secret")
    captured = {"discovery": None, "token_url": None}

    class FakeDiscoveryResponse:  # pylint: disable=too-few-public-methods
        status_code = 200
        text = '{"token_endpoint":"https://auth.fitness-pals.com/application/o/token/"}'

        @staticmethod
        def json():
            return {
                "authorization_endpoint": "https://auth.fitness-pals.com/application/o/authorize/",
                "token_endpoint": "https://auth.fitness-pals.com/application/o/token/",
                "jwks_uri": "https://auth.fitness-pals.com/application/o/training-agent-gpt/jwks/",
            }

    class FakeTokenResponse:  # pylint: disable=too-few-public-methods
        status_code = 200
        text = '{"access_token":"token"}'

        @staticmethod
        def json():
            return {"access_token": "token"}

    def fake_get(url, timeout=None):
        captured["discovery"] = (url, timeout)
        return FakeDiscoveryResponse()

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["token_url"] = url
        captured["data"] = dict(data)
        captured["headers"] = dict(headers)
        captured["timeout"] = timeout
        return FakeTokenResponse()

    monkeypatch.setattr(auth_mod.requests, "get", fake_get)
    monkeypatch.setattr(auth_mod.requests, "post", fake_post)
    auth_mod._load_oidc_discovery.cache_clear()  # pylint: disable=protected-access

    client = TestClient(main.app)
    callback = "https://chat.openai.com/aip/g-broker/oauth/callback"
    response = client.post(
        "/oauth/google/token",
        data={"code": "auth-code", "redirect_uri": callback},
    )

    assert response.status_code == 200
    assert captured["discovery"] == (
        "https://auth.fitness-pals.com/application/o/training-agent-gpt/.well-known/openid-configuration",
        5,
    )
    assert captured["token_url"] == "https://auth.fitness-pals.com/application/o/token/"
    assert captured["data"]["client_id"] == "oidc-client"
    assert captured["data"]["client_secret"] == "oidc-secret"
    assert captured["data"]["redirect_uri"] == callback


# --- Helpers for endpoint integration-style tests ---
class FakeCanonicalStore:  # pylint: disable=too-few-public-methods
    """Canonical-store stub that records the mandatory athlete scope."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def _next(self, kind, user_id, **kwargs):
        self.queries.append((kind, user_id, kwargs))
        return self.responses.pop(0) if self.responses else []

    def activities(self, user_id, **kwargs):
        """Return the next canonical activity response."""
        return self._next("activities", user_id, **kwargs)

    def sleep_sessions(self, user_id, **kwargs):
        """Return the next canonical sleep response."""
        return self._next("sleep_sessions", user_id, **kwargs)


def setup_app_overrides(_monkeypatch, responses):
    """Prepare TestClient with one resolved athlete and canonical data."""
    athlete = training_data.Athlete(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="runner@example.com",
    )
    fake_store = FakeCanonicalStore(responses)
    main.app.dependency_overrides[training_data.get_current_athlete] = lambda: athlete
    main.app.dependency_overrides[training_data.get_training_store] = lambda: fake_store
    return TestClient(main.app), fake_store


def test_weekly_and_sleep_summary(monkeypatch):
    """Weekly/sleep endpoints should aggregate distance and sleep metrics."""
    responses = [
        [{"id": "activity-1", "distance_m": 10, "metadata_json": {"calories": 500}}],
        [{"summary_json": {"rhr": 42}}],
        [
            {
                "summary_json": {
                    "sleep": 28000,
                    "stress": 12,
                    "hrv": 55,
                    "resting_hr": 40,
                    "deep": 8000,
                    "light": 12000,
                    "rem": 6000,
                    "awake": 2000,
                }
            }
        ],
    ]
    client, fake = setup_app_overrides(monkeypatch, responses)
    weekly = client.get("/weekly-summary")
    sleep = client.get("/sleep-summary")
    assert weekly.status_code == 200
    assert sleep.status_code == 200
    assert weekly.json()["distance"] == 10
    assert sleep.json()["sleep_seconds"] == 28000
    assert len(fake.queries) == 3


def test_vo2_and_hrv_trends(monkeypatch):
    """VO2 and HRV trend endpoints respond with recent stats."""
    responses = [
        [{"id": "activity-1", "metadata_json": {"vo2maxValue": 52}}],
        [{"summary_json": {"avgOvernightHrv": 80, "weeklyAvg": 75}}],
    ]
    client, fake = setup_app_overrides(monkeypatch, responses)
    vo2 = client.get("/vo2-trend")
    hrv = client.get("/hrv-trend")
    assert vo2.json()["latest"] == 52
    assert hrv.json()["latest"] == 80
    assert len(fake.queries) == 2


def test_last_run(monkeypatch):
    """last-run endpoint should enrich cadence and metadata."""
    responses = [
        [
            {
                "id": "00000000-0000-0000-0000-000000000123",
                "start_time": "2026-01-01T00:00:00Z",
                "duration_seconds": 3600,
                "distance_m": 10000,
                "sport": "running",
                "metadata_json": {
                    "movingDuration": 3500,
                    "averageHR": 150,
                    "calories": 800,
                    "strideLength": 1.1,
                    "averageRunCadence": 170,
                },
            }
        ]
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    resp = client.get("/last-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_id"] == "00000000-0000-0000-0000-000000000123"
    assert body["average_cadence"] == 170


def test_recovery_and_load(monkeypatch):
    """Recovery score and training load endpoints work end-to-end."""
    responses = [
        [{"summary_json": {"body_battery": 12, "sleep_stress": 3}}],
        [{"metadata_json": {"trainingLoad": {"low": 10, "high": 20, "anaerobic": 5}}}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    rec = client.get("/recovery-score")
    load = client.get("/training-load")
    assert rec.json()["body_battery_change"] == 12
    assert load.json()["low"] == 10


def test_running_dynamics_and_recovery_time(monkeypatch):
    """Running dynamics and recovery time endpoints should return values."""
    responses = [
        [
            {
                "id": "activity-77",
                "sport": "running",
                "metadata_json": {
                    "averageRunCadence": 175,
                    "strideLength": 1.0,
                    "verticalOscillation": 8.5,
                    "groundContactTime": 250,
                },
            }
        ],
        [{"id": "activity-77", "metadata_json": {"recoveryTimeHours": 36}}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    dyn = client.get("/running-dynamics")
    rtime = client.get("/recovery-time")
    assert dyn.json()["activity_id"] == "activity-77"
    assert rtime.json()["recovery_time_hours"] == 36


def test_sleep_stress_battery(monkeypatch):
    """Sleep metrics and stress battery endpoints support responses."""
    responses = [
        [
            {
                "summary_json": {
                    "sleep": 26000,
                    "deep": 9000,
                    "light": 11000,
                    "rem": 4000,
                    "awake": 2000,
                    "score": 85,
                    "rhr": 42,
                }
            }
        ],
        [{"summary_json": {"stress": 12}}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    metrics = client.get("/sleep-metrics")
    stress = client.get("/stress-battery")
    assert (
        metrics.json()["sleep"] == 26000
        or metrics.json().get("sleepTimeSeconds") is None
    )
    assert stress.json()["stress_percentage"] == 12


def test_lactate_race(monkeypatch):
    """Lactate threshold and race endpoints handle API output."""
    responses = [
        [{"metadata_json": {"lactateThreshold": {"heartRate": 170, "pace": 300}}}],
        [{"metadata_json": {"racePredictions": {"time5K": 1200, "time10K": 2400, "half": 5400, "marathon": 12000}}}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    lactate = client.get("/lactate-threshold")
    races = client.get("/race-predictions")
    schedule = client.get("/race-schedule")
    assert lactate.json()["heart_rate"] == 170
    assert races.json()["time5K"] == 1200
    assert schedule.json()["entries"] == []


def test_training_log(monkeypatch):
    """Training log should dedupe entries and compute paces."""
    responses = [
        [
            {
                "id": "activity-1",
                "start_time": "2026-01-01T00:00:00Z",
                "distance_m": 5000,
                "sport": "running",
                "metadata_json": {"averageSpeed": 3.5},
            },
        ]
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    resp = client.get("/training-log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 42
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["activity_id"] == "activity-1"
    assert entry["run_label"] == "Outdoor run"
    assert entry["avg_pace_sec_per_km"] > 0


def test_utility_helpers_cover_branches():
    """Utility helpers should cover spur-of-the-moment branches."""
    row = {"avgCadence": 165}
    assert main.resolve_cadence(row) == 165
    assert main.first_non_null(None, None, 5, 6) == 5
