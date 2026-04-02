"""Tests for LLM client fallback behavior."""

from __future__ import annotations

import httpx

from openai import AuthenticationError

from app.llm import client as llm_client


def test_run_coach_prompt_returns_fallback_on_openai_auth_error(monkeypatch):
    """OpenAI auth errors should degrade to a user-safe fallback response."""

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

    result = llm_client.run_coach_prompt("hello", {"mileage": {}})

    assert result == "Coach unavailable right now."
