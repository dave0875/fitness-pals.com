"""Regression coverage for tenant isolation in training-agent fitness reads."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.training_agent import main
from services.training_agent import training_data


@pytest.fixture
def scoped_client():
    """Build a two-athlete canonical database and expose the training API."""
    main.app.dependency_overrides.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE)"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE activities (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    duration_seconds INTEGER,
                    distance_m FLOAT,
                    sport TEXT,
                    metadata TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE sleep_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    calendar_date DATE NOT NULL,
                    summary_json TEXT
                )
                """
            )
        )

        athlete_a = uuid.uuid4()
        athlete_b = uuid.uuid4()
        connection.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            [
                {"id": str(athlete_a), "email": "athlete-a@example.com"},
                {"id": str(athlete_b), "email": "athlete-b@example.com"},
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO activities
                    (id, user_id, start_time, duration_seconds, distance_m, sport, metadata)
                VALUES
                    (:id, :user_id, :start_time, :duration_seconds, :distance_m, :sport, :metadata)
                """
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(athlete_a),
                    "start_time": datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
                    "duration_seconds": 1800,
                    "distance_m": 5000.0,
                    "sport": "running",
                    "metadata": json.dumps({"name": "Athlete A run", "averageSpeed": 3.0}),
                },
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(athlete_b),
                    "start_time": datetime(2026, 9, 8, 13, tzinfo=timezone.utc),
                    "duration_seconds": 3600,
                    "distance_m": 10000.0,
                    "sport": "running",
                    "metadata": json.dumps({"name": "Athlete B private run", "averageSpeed": 4.0}),
                },
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO sleep_sessions (id, user_id, calendar_date, summary_json)
                VALUES (:id, :user_id, :calendar_date, :summary_json)
                """
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(athlete_a),
                    "calendar_date": date(2026, 9, 8),
                    "summary_json": json.dumps({"sleepTimeSeconds": 25200, "sleepScore": 80}),
                },
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(athlete_b),
                    "calendar_date": date(2026, 9, 8),
                    "summary_json": json.dumps({"sleepTimeSeconds": 32400, "sleepScore": 95}),
                },
            ],
        )

    def db_override():
        with Session(engine) as session:
            yield session

    main.app.dependency_overrides[training_data.get_db] = db_override
    main.app.dependency_overrides[main.require_google_auth] = lambda: {
        "sub": "verified-subject-a",
        "email": "athlete-a@example.com",
        "email_verified": True,
    }
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_authenticated_athlete_cannot_read_another_users_activity(scoped_client):
    """The verified identity, not caller input, owns the activity query scope."""
    response = scoped_client.get(
        "/training-log",
        params={"days": 42, "user_id": "pretend-other-user"},
    )

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["distance_m"] for entry in entries] == [5000.0]
    assert "Athlete B private run" not in response.text


def test_authenticated_athlete_cannot_read_another_users_sleep(scoped_client):
    """Sleep reads apply the same canonical user predicate as activity reads."""
    response = scoped_client.get("/sleep-metrics")

    assert response.status_code == 200
    assert response.json()["sleep"] == 25200
    assert "32400" not in response.text


def test_unmapped_authenticated_subject_is_rejected(scoped_client):
    """A valid external token is insufficient without a canonical user mapping."""
    main.app.dependency_overrides[main.require_google_auth] = lambda: {
        "sub": "unknown-subject",
        "email": "unknown@example.com",
        "email_verified": True,
    }

    response = scoped_client.get("/training-log")

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated athlete is not provisioned"}


def test_authenticated_claim_without_subject_is_rejected(scoped_client):
    """Identity resolution requires the provider's verified subject claim."""
    main.app.dependency_overrides[main.require_google_auth] = lambda: {
        "email": "athlete-a@example.com",
        "email_verified": True,
    }

    response = scoped_client.get("/training-log")

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated athlete is not provisioned"}
