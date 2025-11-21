"""Unit tests for dedupe helpers and ingest transparency endpoints."""

import datetime
import uuid

import pytest
from fastapi import HTTPException

from app.models import IngestDecision, IngestRun
from app.routes import ingest as ingest_routes
from app.services import dedupe


class FakeSession:
    """Minimal session stub used for tests."""

    def __init__(self, items=None):
        """Initialize with optional seeded items."""
        self.items = items or []
        self.added = []

    # SQLAlchemy-like stubs
    def add(self, obj):
        """Record objects added to the session."""
        self.added.append(obj)

    def commit(self):
        """Mimic persistence by assigning UUIDs if missing."""
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        """Return the provided object (no-op)."""
        return obj

    def query(self, model):
        """Pre-seed items of a given model for endpoint testing."""
        data = [i for i in self.items if isinstance(i, model)]
        return FakeQuery(data)


class FakeQuery:
    """Simple query stub to satisfy test expectations."""

    def __init__(self, data):
        self.data = data

    def order_by(self, *_args, **_kwargs):
        """Ignore ordering and return self."""
        return self

    def limit(self, *_):
        """Ignore limit and return self."""
        return self

    def filter(self, *_args, **_kwargs):
        """Ignore filtering and return self."""
        return self

    def all(self):
        """Return all seeded results."""
        return list(self.data)

    def first(self):
        """Return the first seeded result if present."""
        return self.data[0] if self.data else None


def test_fingerprint_variation_with_sport_and_rounded_fields():
    """Fingerprint should change when sport differs but ignore float noise."""
    # Slightly different duration/distance should still change the hash when sport changes
    fp_run = dedupe.fingerprint_activity("2024-01-01T10:00:00Z", 3600.4, 10000.4, "run")
    fp_ride = dedupe.fingerprint_activity("2024-01-01T10:00:00Z", 3600.4, 10000.4, "ride")
    assert fp_run != fp_ride

    # Rounding should normalize insignificant float noise
    fp_noise_a = dedupe.fingerprint_activity("2024-01-01T10:00:00Z", 3600.4, 10000.44, "run")
    fp_noise_b = dedupe.fingerprint_activity("2024-01-01T10:00:00Z", 3600.6, 10000.46, "run")
    assert fp_noise_a == fp_noise_b


def test_record_and_finish_ingest_run_sets_status_and_times():
    """record_ingest_run/finish_ingest_run should set metadata."""
    db = FakeSession()
    run = dedupe.record_ingest_run(db, provider="garmin")
    assert run.status == "running"
    assert run.provider == "garmin"
    assert run.started_at is not None

    finished = dedupe.finish_ingest_run(db, run, status="completed", summary={"new": 1})
    assert finished.status == "completed"
    assert finished.finished_at is not None
    assert finished.summary == {"new": 1}


def test_log_decision_persists_reason_and_fingerprint():
    """log_decision should persist reason, fingerprint, and tolerances."""
    db = FakeSession()
    run = IngestRun(
        id=uuid.uuid4(),
        provider="strava",
        status="running",
        started_at=datetime.datetime.utcnow(),
    )

    details = dedupe.DecisionDetails(
        user_id=uuid.uuid4(),
        provider="strava",
        provider_activity_id="abc123",
        decision="duplicate",
        reason="matched fingerprint",
        fingerprint={"start": "2024-01-01T00:00:00Z"},
        tolerances={"start": 90},
        chosen_fields={"distance_m": "garmin"},
    )
    recorded = dedupe.log_decision(db, run, details)
    assert recorded.decision == "duplicate"
    assert recorded.reason == "matched fingerprint"
    assert recorded.provider_activity_id == "abc123"
    assert recorded.fingerprint["start"] == "2024-01-01T00:00:00Z"
    assert recorded.tolerances["start"] == 90
    assert recorded.chosen_fields["distance_m"] == "garmin"


def test_ingest_endpoints_list_runs_and_decisions():
    """Ingest endpoints should list runs and their decisions."""
    user_id = uuid.uuid4()
    run = IngestRun(
        id=uuid.uuid4(),
        provider="garmin",
        status="completed",
        started_at=datetime.datetime.utcnow(),
        finished_at=datetime.datetime.utcnow(),
        summary={"new": 2},
    )
    decision = IngestDecision(
        id=uuid.uuid4(),
        ingest_run_id=run.id,
        user_id=user_id,
        provider="garmin",
        provider_activity_id="act1",
        activity_id=uuid.uuid4(),
        decision="merged",
        reason="matched time/distance",
        fingerprint={"start": "2024-01-01T00:00:00Z"},
        tolerances={"start": 90},
        chosen_fields={"hr": "garmin"},
        created_at=datetime.datetime.utcnow(),
    )
    db = FakeSession(items=[run, decision])
    user = type("User", (), {"id": user_id})()

    runs = ingest_routes.list_runs(user, db=db)
    assert runs and runs[0]["id"] == str(run.id)
    assert runs[0]["summary"] == {"new": 2}

    fetched_run = ingest_routes.get_run(str(run.id), user, db=db)
    assert fetched_run["status"] == "completed"

    decisions = ingest_routes.list_decisions(str(run.id), user, db=db)
    assert decisions and decisions[0]["provider_activity_id"] == "act1"
    assert decisions[0]["decision"] == "merged"
    assert decisions[0]["chosen_fields"]["hr"] == "garmin"


def test_ingest_get_run_not_found_raises_http():
    """Requesting a missing run should raise HTTPException."""
    db = FakeSession(items=[])
    user = type("User", (), {"id": uuid.uuid4()})()
    with pytest.raises(HTTPException):
        ingest_routes.get_run(str(uuid.uuid4()), user, db=db)
