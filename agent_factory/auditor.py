from __future__ import annotations

from typing import Dict, List


class BlueprintAuditor:
    """
    Validates new agent proposal payloads before generation/registration.
    """

    REQUIRED_FIELDS = {"name", "description", "capabilities"}

    @classmethod
    def validate(cls, proposal: Dict) -> List[str]:
        errors: List[str] = []
        missing = cls.REQUIRED_FIELDS - proposal.keys()
        if missing:
            errors.append(f"Missing fields: {', '.join(sorted(missing))}")
        if "capabilities" in proposal and not proposal["capabilities"]:
            errors.append("Capabilities must not be empty")
        return errors
