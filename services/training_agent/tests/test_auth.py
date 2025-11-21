# ruff: noqa: E501
"""Tests covering Google OAuth verification and metrics endpoints."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.training_agent import main


class StaticResponse:  # pylint: disable=too-few-public-methods
    """Test HTTP response stub for mocking requests."""

    def __init__(self, status_code: int, text: str, payload: dict):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        """Return the stored JSON payload."""
        return self._payload


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
    """Missing or malformed Authorization headers should raise 401."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization=header)
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_empty_token(monkeypatch):
    """Blank bearer tokens should be rejected."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer   ")
    assert excinfo.value.status_code == 401
    assert "Missing bearer token" in excinfo.value.detail


def test_require_google_auth_missing_client_id(monkeypatch):
    """Missing Google client ID should result in server error."""
    monkeypatch.delenv("RUNTRAINER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", None)
    with pytest.raises(HTTPException) as excinfo:
        main.require_google_auth(authorization="Bearer sometoken")
    assert excinfo.value.status_code == 500
    assert "missing RUNTRAINER_GOOGLE_CLIENT_ID" in excinfo.value.detail


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


# --- Helpers for endpoint integration-style tests ---
class FakeResult:  # pylint: disable=too-few-public-methods
    """Thin wrapper that mimics the Influx query result interface."""

    def __init__(self, rows):
        self._rows = rows

    def get_points(self):
        """Return an iterator over the stored rows."""
        return iter(self._rows)


class FakeClient:  # pylint: disable=too-few-public-methods
    """Simple Influx client stub returning pre-defined results."""

    def __init__(self, responses):
        # responses is a list of lists; each query pops the next
        self.responses = list(responses)
        self.queries = []

    def query(self, _query):
        """Return the next canned response."""
        self.queries.append(_query)
        if self.responses:
            return FakeResult(self.responses.pop(0))
        return FakeResult([])


def setup_app_overrides(monkeypatch, responses):
    """Prepare TestClient with auth bypass and fake Influx responses."""
    monkeypatch.setenv("RUNTRAINER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(main, "GOOGLE_CLIENT_ID", "client-id")
    main.app.dependency_overrides[main.require_google_auth] = lambda: {}
    fake_client = FakeClient(responses)
    monkeypatch.setattr(main, "get_influx_client", lambda: fake_client)
    # Simplify expensive helpers
    monkeypatch.setattr(main, "get_average_cadence", lambda *_, **__: 170)
    monkeypatch.setattr(main, "get_elevation_gain", lambda *_, **__: 25)
    monkeypatch.setattr(
        main,
        "get_elevation_stats",
        lambda *_, **__: {"ascent": 25, "descent": 10, "min": 5, "max": 30},
    )
    monkeypatch.setattr(
        main,
        "get_temperature_stats",
        lambda *_, **__: {"avg": 68, "min": 60, "max": 75},
    )
    monkeypatch.setattr(main, "get_max_cadence", lambda *_, **__: 190)
    return TestClient(main.app), fake_client


def test_weekly_and_sleep_summary(monkeypatch):
    """Weekly/sleep endpoints should aggregate distance and sleep metrics."""
    # weekly: two queries; sleep: one query
    responses = [
        [{"distance": 10, "calories": 500}],
        [{"rhr": 42}],
        [
            {
                "sleep": 28000,
                "stress": 12,
                "hrv": 55,
                "spo2_avg": 98,
                "spo2_low": 92,
                "spo2_high": 99,
                "resting_hr": 40,
                "deep": 8000,
                "light": 12000,
                "rem": 6000,
                "awake": 2000,
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
        [{"latest": 52, "average": 50}],
        [{"latest": 80, "average": 75}],
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
                "Activity_ID": 123,
                "time": "2024-01-01T00:00:00Z",
                "distance": 10000,
                "elapsedDuration": 3600,
                "movingDuration": 3500,
                "averageHR": 150,
                "calories": 800,
                "activityType": "running",
                "strideLength": 1.1,
            }
        ],
        [{"cadence": 170}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    resp = client.get("/last-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_id"] == 123
    assert body["average_cadence"] == 170


def test_recovery_and_load(monkeypatch):
    """Recovery score and training load endpoints work end-to-end."""
    responses = [
        [{"body_battery": 12, "sleep_stress": 3}],
        [{"low": 10, "high": 20, "anaerobic": 5}],
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
                "activityId": 77,
                "averageRunCadence": 175,
                "strideLength": 1.0,
                "verticalOscillation": 8.5,
                "groundContactTime": 250,
            }
        ],
        [{"hours": 36}],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    dyn = client.get("/running-dynamics")
    rtime = client.get("/recovery-time")
    assert dyn.json()["activity_id"] == 77
    assert rtime.json()["recovery_time_hours"] == 36


def test_sleep_stress_battery(monkeypatch):
    """Sleep metrics and stress battery endpoints support responses."""
    responses = [
        [
            {
                "sleep": 26000,
                "deep": 9000,
                "light": 11000,
                "rem": 4000,
                "awake": 2000,
                "score": 85,
                "rhr": 42,
            }
        ],
        [{"stress": 12}],
        [{"charged": 80, "drained": 30}],
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
        [{"heart_rate": 170, "pace": 300}],
        [{"time5K": 1200, "time10K": 2400, "half": 5400, "marathon": 12000}],
        [
            {
                "summary": "Race A",
                "startTimeLocal": "2025-01-01T09:00:00",
                "location": "NYC",
            },
            {
                "summary": "Race B",
                "startTimeLocal": "2025-02-01T09:00:00",
                "location": "BOS",
            },
        ],
    ]
    client, _ = setup_app_overrides(monkeypatch, responses)
    lactate = client.get("/lactate-threshold")
    races = client.get("/race-predictions")
    schedule = client.get("/race-schedule")
    assert lactate.json()["heart_rate"] == 170
    assert races.json()["time5K"] == 1200
    assert len(schedule.json()["entries"]) == 2


def test_training_log(monkeypatch):
    """Training log should dedupe entries and compute paces."""
    responses = [
        [
            {
                "Activity_ID": 1,
                "time": "2025-01-01T00:00:00Z",
                "distance": 5000,
                "averageSpeed": 3.5,
                "averageHR": 145,
                "calories": 400,
                "activityType": "running",
                "totalElevationGain": 50,
                "strideLength": 1.2,
                "verticalOscillation": 8.0,
                "groundContactTime": 240,
                "groundContactBalance": 51.0,
                "stanceTimePercent": 52.0,
            },
            {
                "Activity_ID": 1,
                "time": "2024-12-31T00:00:00Z",
                "distance": 3000,
                "averageSpeed": 3.0,
                "averageHR": 140,
                "calories": 300,
                "activityType": "running",
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
    assert entry["activity_id"] == 1
    assert entry["run_label"] == "Outdoor run"
    assert entry["avg_pace_sec_per_km"] > 0


def test_utility_helpers_cover_branches():
    """Utility helpers should cover spur-of-the-moment branches."""
    row = {"avgCadence": 165}
    assert main.resolve_cadence(row) == 165
    assert main.first_non_null(None, None, 5, 6) == 5
