"""Static validation helpers for blueprint submissions."""

from __future__ import annotations

from typing import Dict, List


class BlueprintAuditor:
    """Validates new agent proposal payloads before generation/registration."""

    REQUIRED_FIELDS = {"name", "description", "capabilities"}

    @classmethod
    def validate(cls, proposal: Dict) -> List[str]:
        """Return a list of validation errors for the proposed agent blueprint."""
        errors: List[str] = []
        missing = cls.REQUIRED_FIELDS - proposal.keys()
        if missing:
            errors.append(f"Missing fields: {', '.join(sorted(missing))}")
        if "capabilities" in proposal and not proposal["capabilities"]:
            errors.append("Capabilities must not be empty")
        return errors

    @classmethod
    def is_valid(cls, proposal: Dict) -> bool:
        """Boolean helper wrapped around :meth:`validate` for simple checks."""
        return not cls.validate(proposal)
