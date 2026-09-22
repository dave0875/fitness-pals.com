"""HTTP-level path from goal selection through the next coaching decision."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.deps import get_current_user
from app.main import app
from app.models import Activity, AthleteGoal, NextSessionPlan
from app.services import today_plan as today_plan_service


def test_dashboard_api_path_reaches_completed_and_next_action_state(monkeypatch):
    """Exercise the real authenticated route contract used by the dashboard."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (Activity.__table__, AthleteGoal.__table__, NextSessionPlan.__table__):
        table.create(engine)
    monkeypatch.setattr(
        today_plan_service,
        "build_athlete_home",
        lambda *_args, **_kwargs: {
            "freshness": {
                "signals": {
                    "activities": {"state": "fresh", "data_through": None},
                    "sleep": {"state": "unknown", "data_through": None},
                    "intensity": {"state": "unknown", "data_through": None},
                }
            }
        },
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    athlete_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    for days_ago, miles, minutes in ((2, 3.5, 31), (4, 4.0, 37)):
        db.add(
            Activity(
                id=uuid.uuid4(),
                user_id=athlete_id,
                start_time=now - timedelta(days=days_ago),
                duration_seconds=minutes * 60,
                distance_m=miles * 1609.344,
                sport="run",
                status="merged",
                fingerprint_hash=str(uuid.uuid4()),
                metadata_json={"name": "Run"},
            )
        )
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=athlete_id)
    client = TestClient(app)
    try:
        assert client.get("/api/today-plan").json()["state"] == "goal_required"
        selected = client.put(
            "/api/today-plan/goal",
            json={
                "goal_type": "consistency",
                "phase": "maintenance",
                "target_date": None,
            },
        )
        assert selected.status_code == 200
        plan_id = selected.json()["plan"]["id"]

        accepted = client.patch(
            f"/api/today-plan/{plan_id}",
            json={"action": "accept", "payload": {}},
        )
        assert accepted.json()["state"] == "accepted"

        saved_plan = db.query(NextSessionPlan).filter(NextSessionPlan.id == uuid.UUID(plan_id)).one()
        matching = Activity(
            id=uuid.uuid4(),
            user_id=athlete_id,
            start_time=saved_plan.created_at + timedelta(seconds=1),
            duration_seconds=27 * 60,
            distance_m=2.75 * 1609.344,
            sport="run",
            status="merged",
            fingerprint_hash=str(uuid.uuid4()),
            metadata_json={"name": "Easy run"},
        )
        db.add(matching)
        db.commit()
        context = client.get("/api/today-plan/context")
        assert context.status_code == 200
        assert len(context.json()["week"]["days"]) == 7
        assert context.json()["match"]["id"] == str(matching.id)

        completed = client.patch(
            f"/api/today-plan/{plan_id}",
            json={
                "action": "complete",
                "payload": {
                    "perceived_effort": "as_expected",
                    "note": "Felt controlled.",
                    "matched_activity_id": str(matching.id),
                },
            },
        )
        assert completed.json()["state"] == "completed"
        assert completed.json()["plan"]["feedback"]["completion_source"] == "canonical_match"
        assert completed.json()["next_decision_available"] is True

        next_decision = client.post("/api/today-plan/next")
        assert next_decision.json()["state"] == "recommended"
        assert next_decision.json()["plan"]["id"] != plan_id
    finally:
        app.dependency_overrides.clear()
        db.close()
        for table in (NextSessionPlan.__table__, AthleteGoal.__table__, Activity.__table__):
            table.drop(engine)
