"""Tests for explicit Coach model failure behavior."""

from __future__ import annotations

import httpx
import pytest

from openai import AuthenticationError

from app.llm import client as llm_client


def test_run_coach_prompt_raises_retryable_error_on_openai_auth_error(monkeypatch):
    """Transport/auth failures must not be persisted as successful coaching prose."""

    class FakeResponses:
        def create(self, **_kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            response = httpx.Response(401, request=request)
            raise AuthenticationError("bad key", response=response, body={})

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key
            self.responses = FakeResponses()

    monkeypatch.setattr(llm_client.settings, "openai_api_key", "bad-key")
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    with pytest.raises(llm_client.CoachUnavailableError):
        llm_client.run_coach_prompt("hello", {"mileage": {}})


def test_run_coach_prompt_requires_configured_model(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "openai_api_key", "")
    with pytest.raises(llm_client.CoachUnavailableError):
        llm_client.run_coach_prompt("hello", {"mileage": {}})
