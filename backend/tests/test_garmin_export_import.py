"""Tests for safe multi-athlete Garmin export import."""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")

from app.models import Activity, PublishedDossier, User
from app.services import garmin_export_import


class FakeSession:
    """Minimal SQLAlchemy-like session for import tests."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
        return None

    def refresh(self, obj):
        return obj

    def rollback(self):
        return None

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


class FakeQuery:
    """Subset of SQLAlchemy query behavior used by the import service."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.items:
            if all(self._matches(condition, item) for condition in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None

    @staticmethod
    def _resolve_value(side, item):
        if isinstance(side, BindParameter):
            return side.value
        attr = getattr(side, "key", None) or getattr(side, "name", None)
        if attr and hasattr(item, attr):
            return getattr(item, attr)
        return side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            if condition.operator is operators.and_:
                return all(self._matches(c, item) for c in condition.clauses)
            if condition.operator is operators.or_:
                return any(self._matches(c, item) for c in condition.clauses)
        if isinstance(condition, BinaryExpression):
            left = self._resolve_value(condition.left, item)
            right = self._resolve_value(condition.right, item)
            if (
                getattr(condition.operator, "__name__", "") == "is_"
                and getattr(right, "__visit_name__", "") == "null"
            ):
                return left is None
            return condition.operator(left, right)
        return True


def _user(email: str, name: str) -> User:
    return User(id=uuid.uuid4(), email=email, name=name)


def _activity(user_id, provider_activity_id: str) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        ingest_run_id=None,
        start_time=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        duration_seconds=1800,
        distance_m=5000.0,
        sport="run",
        status="completed",
        fingerprint_hash=provider_activity_id,
        metadata_json={"provider_activity_id": provider_activity_id},
    )


def _archive_bytes(
    *,
    athlete_name: str,
    emails: list[str],
    contact_emails: list[str] | None = None,
    include_username: bool = True,
    primary_email_as_object: bool = False,
) -> bytes:
    payload = io.BytesIO()
    contact_emails = list(contact_emails or emails)
    primary_email = emails[0]
    primary_email_value = {"emailAddress": primary_email} if primary_email_as_object else primary_email
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "customer_data/customer.json",
            json.dumps(
                {
                    "fullName": athlete_name,
                    "displayName": athlete_name,
                    "primaryEmailAddress": primary_email_value,
                    "username": primary_email if include_username else None,
                }
            ),
        )
        archive.writestr(
            "DI_CONNECT/DI-Connect-User/user_contact.json",
            json.dumps(
                [
                    {
                        "firstName": athlete_name.split()[0],
                        "lastName": athlete_name.split()[-1],
                        "emails": contact_emails,
                    }
                ]
            ),
        )
        archive.writestr(
            "DI_CONNECT/DI-Connect-Fitness/sample_0_summarizedActivities.json",
            json.dumps(
                [
                    {
                        "summarizedActivitiesExport": [
                            {
                                "activityId": 1001,
                                "name": "Morning Run",
                                "activityType": "running",
                                "sportType": "RUNNING",
                                "startTimeGmt": 1713070800000,
                                "duration": 1800000,
                                "distance": 500000.0,
                            },
                            {
                                "activityId": 1002,
                                "name": "Long Run",
                                "activityType": "running",
                                "sportType": "RUNNING",
                                "startTimeGmt": 1713157200000,
                                "duration": 5400000,
                                "distance": 2109750.0,
                            },
                        ]
                    }
                ]
            ),
        )
    return payload.getvalue()


def test_import_rejects_export_for_different_athlete_email():
    """A signed-in athlete cannot import another athlete's archive into their account."""
    db = FakeSession()
    athlete = _user("athlete@example.com", "Athlete One")

    with pytest.raises(HTTPException, match="belongs to another athlete"):
        garmin_export_import.import_garmin_export_archive(
            db=db,
            user=athlete,
            filename="Garmin Export.zip",
            archive_bytes=_archive_bytes(
                athlete_name="Priya Hariani",
                emails=["priya.hariani@gmail.com", "priya@blackspark.com"],
            ),
        )


def test_import_persists_only_current_users_history_and_creates_dossier():
    """Import should stay within the signed-in user's boundary and publish one dossier."""
    athlete = _user("priya.hariani@gmail.com", "Priya Hariani")
    other_user = _user("dave0875@gmail.com", "Dave Barker")
    existing_other_activity = _activity(other_user.id, "existing-dave-run")
    db = FakeSession([existing_other_activity])

    result = garmin_export_import.import_garmin_export_archive(
        db=db,
        user=athlete,
        filename="Garmin Export.zip",
        archive_bytes=_archive_bytes(
            athlete_name="Priya Hariani",
            emails=["priya.hariani@gmail.com", "priya@blackspark.com"],
        ),
    )

    athlete_activities = [
        item for item in db.items if isinstance(item, Activity) and item.user_id == athlete.id
    ]
    other_activities = [
        item for item in db.items if isinstance(item, Activity) and item.user_id == other_user.id
    ]
    dossiers = [item for item in db.items if isinstance(item, PublishedDossier)]

    assert result["activity_count"] == 2
    assert len(athlete_activities) == 2
    assert len(other_activities) == 1
    assert len(dossiers) == 1
    assert dossiers[0].user_id == athlete.id
    assert dossiers[0].slug == "priya-hariani-garmin-archive-dossier"
    assert "Priya Hariani" in dossiers[0].title


def test_import_ignores_contact_list_emails_when_matching_athlete_identity():
    """Archive contact emails should not block import for the signed-in athlete."""
    athlete = _user("gaurav.hariani@gmail.com", "Gaurav Hariani")
    db = FakeSession()

    result = garmin_export_import.import_garmin_export_archive(
        db=db,
        user=athlete,
        filename="Garmin Export.zip",
        archive_bytes=_archive_bytes(
            athlete_name="Gaurav Hariani",
            emails=["gaurav.hariani@gmail.com"],
            contact_emails=["priya.hariani@gmail.com", "pavinder40@hotmail.com"],
        ),
    )

    dossiers = [item for item in db.items if isinstance(item, PublishedDossier)]

    assert result["activity_count"] == 2
    assert len(dossiers) == 1
    assert dossiers[0].slug == "gaurav-hariani-garmin-archive-dossier"


def test_import_accepts_primary_email_address_object_shape():
    """Garmin customer exports can nest the primary email inside an object."""
    athlete = _user("gaurav.hariani@gmail.com", "Gaurav Hariani")
    db = FakeSession()

    result = garmin_export_import.import_garmin_export_archive(
        db=db,
        user=athlete,
        filename="Garmin Export.zip",
        archive_bytes=_archive_bytes(
            athlete_name="Gaurav Hariani",
            emails=["gaurav.hariani@gmail.com"],
            include_username=False,
            primary_email_as_object=True,
        ),
    )

    assert result["activity_count"] == 2


def test_import_is_idempotent_for_replayed_archive():
    """Reimporting the same archive should update one dossier without duplicating activities."""
    athlete = _user("priya.hariani@gmail.com", "Priya Hariani")
    db = FakeSession()
    archive_bytes = _archive_bytes(
        athlete_name="Priya Hariani",
        emails=["priya.hariani@gmail.com", "priya@blackspark.com"],
    )

    first = garmin_export_import.import_garmin_export_archive(
        db=db, user=athlete, filename="Garmin Export.zip", archive_bytes=archive_bytes
    )
    second = garmin_export_import.import_garmin_export_archive(
        db=db, user=athlete, filename="Garmin Export.zip", archive_bytes=archive_bytes
    )

    athlete_activities = [
        item for item in db.items if isinstance(item, Activity) and item.user_id == athlete.id
    ]
    dossiers = [item for item in db.items if isinstance(item, PublishedDossier)]

    assert first["activity_count"] == 2
    assert second["activity_count"] == 2
    assert len(athlete_activities) == 2
    assert len(dossiers) == 1
