from __future__ import annotations

from typing import Dict


SYSTEM_HINT = (
    "You are Codex, a coding agent. Generate ONLY the incremental code needed to add the new agent. "
    "Do not restate or rebuild existing Run Trainer architecture. Use GPT-5.1 for all completions."
)


def generate_coding_prompt(proposal: Dict, repo_notes: str = "") -> str:
    """
    Builds a focused prompt for Codex to implement the new agent without duplicating existing code.
    """
    name = proposal.get("name", "New Agent")
    desc = proposal.get("description", "")
    caps = proposal.get("capabilities", [])
    prompt = f"""{SYSTEM_HINT}

Agent name: {name}
Summary: {desc}
Capabilities: {caps}
Repository notes (do not duplicate): {repo_notes}

Instructions:
- Add only new agent scaffolding.
- Do not touch OAuth, JWT, Run Trainer metrics, or existing models.
- Target model: GPT-5.1.
"""
    return prompt.strip()
