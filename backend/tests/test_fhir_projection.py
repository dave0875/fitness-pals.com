"""Slice 9 red tests for the first FHIR projection seam."""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timezone

import pytest

os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")

from app.models import Activity


def _load_projection_module():
    """Load the expected FHIR projection seam if it exists."""
    try:
        return importlib.import_module("app.services.fhir_projection")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "Expected a FHIR projection/export seam at app.services.fhir_projection"
        ) from exc


def _make_activity():
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    return Activity(
        id=activity_id,
        user_id=user_id,
        start_time=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc),
        duration_seconds=3600,
        distance_m=16093.4,
        sport="run",
        status="merged",
        fingerprint_hash=f"activity-{activity_id}",
        metadata_json={"source": "canonical"},
    )


def test_activity_projection_is_deterministic_with_a_stable_id():
    """Projecting the same canonical activity should always produce the same FHIR id."""
    projection = _load_projection_module()
    activity = _make_activity()

    project_activity = getattr(projection, "project_activity", None)
    if project_activity is None:
        pytest.fail("Expected project_activity(activity) in the FHIR projection seam")

    first = project_activity(activity)
    second = project_activity(activity)

    assert first["resourceType"] == "Observation"
    assert first["id"] == second["id"]
    assert first["id"] == str(activity.id)


def test_activity_projection_is_idempotent_for_repeated_projection_calls():
    """Projecting the same canonical entity repeatedly should not change the resource."""
    projection = _load_projection_module()
    activity = _make_activity()

    project_activity = getattr(projection, "project_activity", None)
    if project_activity is None:
        pytest.fail("Expected project_activity(activity) in the FHIR projection seam")

    first = project_activity(activity)
    second = project_activity(activity)

    assert first == second
    assert first["identifier"][0]["value"] == str(activity.id)
    assert first["effectiveDateTime"] == activity.start_time.isoformat()


def test_activity_projection_does_not_mutate_canonical_product_data():
    """The export seam should not rewrite the canonical Activity row."""
    projection = _load_projection_module()
    activity = _make_activity()
    original = {
        "id": activity.id,
        "user_id": activity.user_id,
        "start_time": activity.start_time,
        "duration_seconds": activity.duration_seconds,
        "distance_m": activity.distance_m,
        "sport": activity.sport,
        "status": activity.status,
        "fingerprint_hash": activity.fingerprint_hash,
        "metadata_json": activity.metadata_json.copy()
        if activity.metadata_json
        else None,
    }

    project_activity = getattr(projection, "project_activity", None)
    if project_activity is None:
        pytest.fail("Expected project_activity(activity) in the FHIR projection seam")

    result = project_activity(activity)

    assert isinstance(result, dict)
    assert activity.id == original["id"]
    assert activity.user_id == original["user_id"]
    assert activity.start_time == original["start_time"]
    assert activity.duration_seconds == original["duration_seconds"]
    assert activity.distance_m == original["distance_m"]
    assert activity.sport == original["sport"]
    assert activity.status == original["status"]
    assert activity.fingerprint_hash == original["fingerprint_hash"]
    assert activity.metadata_json == original["metadata_json"]
