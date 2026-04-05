"""Pure FHIR projection helpers for canonical product entities."""

from __future__ import annotations

from typing import Any


def project_activity(activity: Any) -> dict[str, Any]:
    """Project a canonical Activity into a deterministic FHIR Observation."""
    activity_id = str(activity.id)
    resource = {
        "resourceType": "Observation",
        "id": activity_id,
        "identifier": [
            {
                "system": "urn:fitness-pals:activity",
                "value": activity_id,
            }
        ],
        "status": "final",
        "code": {
            "text": "Activity summary",
        },
        "subject": {
            "reference": f"Patient/{activity.user_id}",
        },
        "effectiveDateTime": activity.start_time.isoformat(),
        "valueQuantity": {
            "value": activity.distance_m,
            "unit": "m",
            "system": "http://unitsofmeasure.org",
            "code": "m",
        },
    }
    if activity.duration_seconds is not None:
        resource["component"] = [
            {
                "code": {"text": "duration"},
                "valueQuantity": {
                    "value": activity.duration_seconds,
                    "unit": "s",
                    "system": "http://unitsofmeasure.org",
                    "code": "s",
                },
            }
        ]
    if activity.sport:
        resource["category"] = [{"text": str(activity.sport)}]
    return resource
