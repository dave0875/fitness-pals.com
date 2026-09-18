"""Utility for invoking the OpenAI client with guardrails."""

from __future__ import annotations

from typing import Any, Dict, cast

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

from app.config import get_settings

settings = get_settings()


def run_coach_prompt(message: str, metrics: Dict) -> str:
    """Call the configured OpenAI model and return the textual response."""
    if not settings.openai_api_key:
        return "LLM not configured."
    client = cast(Any, OpenAI(api_key=settings.openai_api_key))
    prompt = (
        "You are a multi-user running coach. Use only data provided by tool calls. "
        "Never hallucinate running activities. Invalid or missing distance is unknown, not zero. "
        "Do not call training volume readiness or give recovery-based recommendations when recovery "
        "and intensity are unavailable. Provide concise, cautious guidance.\n"
        f"User metrics: {metrics}\nUser message: {message}"
    )
    try:
        resp = client.responses.create(  # pylint: disable=no-member
            model="gpt-4.1",
            input=[
                {"role": "system", "content": prompt},
            ],
            max_output_tokens=300,
        )
    except (AuthenticationError, APIConnectionError, APIStatusError):
        return "Coach unavailable right now."
    return resp.output_text if hasattr(resp, "output_text") else resp.output[0].content[0].text
