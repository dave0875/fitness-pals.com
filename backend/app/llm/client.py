"""Utility for invoking the OpenAI client with explicit failure semantics."""

from __future__ import annotations

from typing import Any, Dict, cast

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

from app.config import get_settings

settings = get_settings()


class CoachUnavailableError(RuntimeError):
    """Raised when Coach cannot produce an answer safe to persist as success."""


def run_coach_prompt(message: str, metrics: Dict) -> str:
    """Call the configured model with bounded canonical context."""
    if not settings.openai_api_key:
        raise CoachUnavailableError("Coach model is not configured")

    client = cast(Any, OpenAI(api_key=settings.openai_api_key))
    prompt = (
        "You are the athlete's running coach. Use only the canonical context supplied here. "
        "Never invent activities, recovery signals, or measurements. Invalid or missing distance "
        "is unknown, not zero. Do not call training volume readiness or give recovery-based "
        "recommendations when recovery and intensity are unavailable. The attached evidence and "
        "conversation history are bounded context, not permission to infer missing facts. "
        "Distinguish measured facts, derived metrics, model outputs, and your coaching "
        "interpretation in plain language. Hypothetical scenarios are projections, not observed facts, "
        "and must stay labeled as such. Athlete-to-self associations are correlations only; never claim "
        "they establish causation. Deliberate coaching preferences may guide style or choices, but do not "
        "invent or infer preferences that are not supplied. Keep the answer concise and actionable.\n"
        f"Coach context: {metrics}\nAthlete message: {message}"
    )
    try:
        resp = client.responses.create(  # pylint: disable=no-member
            model="gpt-4.1",
            input=[{"role": "system", "content": prompt}],
            max_output_tokens=300,
        )
    except (AuthenticationError, APIConnectionError, APIStatusError) as exc:
        raise CoachUnavailableError("Coach model is unavailable") from exc

    text = (
        resp.output_text
        if hasattr(resp, "output_text")
        else resp.output[0].content[0].text
    )
    if not isinstance(text, str) or not text.strip():
        raise CoachUnavailableError("Coach returned an empty response")
    return text.strip()
