from __future__ import annotations

from typing import Dict

from openai import OpenAI

from app.config import get_settings

settings = get_settings()


def run_coach_prompt(message: str, metrics: Dict) -> str:
    if not settings.openai_api_key:
        return "LLM not configured."
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = (
        "You are a multi-user running coach. Use only data provided by tool calls. "
        "Never hallucinate running activities. Provide concise, actionable guidance.\n"
        f"User metrics: {metrics}\nUser message: {message}"
    )
    resp = client.responses.create(
        model="gpt-4.1",
        input=[
            {"role": "system", "content": prompt},
        ],
        max_output_tokens=300,
    )
    return resp.output_text if hasattr(resp, "output_text") else resp.output[0].content[0].text
