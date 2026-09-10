"""Drive archive source, checkpoint, dedupe, and ownership tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter

from app.models import Activity, ArchiveImportJob, ArchiveImportObject, IngestRun, User
from app.services import archive_import_jobs
from app.services.garmin.activity import persist_activity_summaries
from app.services.garmin_archive_import import ingest_archive_object
from app.services.google_drive_archive import DriveArchiveObject, configured_folder_for_user


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *conditions):
        return FakeQuery(
            item
            for item in self.items
            if all(self._matches(condition, item) for condition in conditions)
        )

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)

    @staticmethod
    def _value(side, item):
        if isinstance(side, BindParameter):
            return side.value
        key = getattr(side, "key", None) or getattr(side, "name", None)
        return getattr(item, key) if key and hasattr(item, key) else side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            clauses = [self._matches(part, item) for part in condition.clauses]
            return all(clauses) if condition.operator is operators.and_ else any(clauses)
        if isinstance(condition, BinaryExpression):
            return condition.operator(self._value(condition.left, item), self._value(condition.right, item))
        return True


class FakeSession:
    def __init__(self, items=()):
        self.items = list(items)

    def add(self, item):
        self.items.append(item)

    def commit(self):
        for item in self.items:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    def refresh(self, _item):
        return None

    def query(self, model):
        return FakeQuery(item for item in self.items if isinstance(item, model))

    def get(self, model, object_id):
        return next(
            (item for item in self.items if isinstance(item, model) and item.id == object_id),
            None,
        )


def _user(email="runner@example.com"):
    return User(id=uuid.uuid4(), email=email, name="Runner")


def _settings(mapping):
    return SimpleNamespace(google_drive_archive_sources_json=json.dumps(mapping))


def test_drive_folder_assignment_is_server_side_and_athlete_specific():
    first = _user("one@example.com")
    second = _user("two@example.com")
    settings = _settings({"one@example.com": "folder-one", "two@example.com": "folder-two"})

    assert configured_folder_for_user(first, settings=settings) == "folder-one"
    assert configured_folder_for_user(second, settings=settings) == "folder-two"

    with pytest.raises(HTTPException, match="not configured"):
        configured_folder_for_user(_user("missing@example.com"), settings=settings)


def test_drive_job_checkpoints_each_version_and_replay_is_idempotent(monkeypatch):
    athlete = _user()
    db = FakeSession([athlete])
    source_object = DriveArchiveObject(
        object_id="drive-file-1",
        name="2026-09-09-18-49-13.fit",
        mime_type="application/fits",
        version="md5-version-1",
        modified_time="2026-09-09T23:58:02Z",
        size_bytes=153050,
    )
    fake_drive = SimpleNamespace(
        list_supported_objects=lambda _folder_id: [source_object],
        download=lambda _object: b"fit-bytes",
    )
    imported = []

    monkeypatch.setattr(archive_import_jobs, "_drive_client", lambda: fake_drive)
    monkeypatch.setattr(
        archive_import_jobs,
        "ingest_archive_object",
        lambda **kwargs: imported.append(kwargs) or {"activity_count": 1},
    )

    job = archive_import_jobs.create_drive_import_job(db, athlete, folder_id="folder-one")
    first = archive_import_jobs.process_archive_import_job(db, job)

    replay = ArchiveImportJob(
        user_id=athlete.id,
        provider="garmin_archive",
        source_type="google_drive",
        source_locator="folder-one",
        status="queued",
        filename="Google Drive Garmin archive",
        content_type="application/vnd.google-apps.folder",
        size_bytes=0,
        storage_backend="google_drive",
        storage_key=f"google-drive/{athlete.id}/replay",
    )
    db.add(replay)
    db.commit()
    second = archive_import_jobs.process_archive_import_job(db, replay)

    checkpoints = [item for item in db.items if isinstance(item, ArchiveImportObject)]
    assert first["objects_imported"] == 1
    assert second["objects_skipped"] == 1
    assert len(imported) == 1
    assert len(checkpoints) == 1
    assert checkpoints[0].user_id == athlete.id
    assert checkpoints[0].source_object_id == "drive-file-1"
    assert checkpoints[0].source_version == "md5-version-1"
    assert checkpoints[0].status == "completed"


def test_same_drive_object_isolated_per_athlete(monkeypatch):
    first = _user("one@example.com")
    second = _user("two@example.com")
    checkpoint = ArchiveImportObject(
        job_id=uuid.uuid4(),
        user_id=first.id,
        provider="garmin_archive",
        source_type="google_drive",
        source_object_id="same-object",
        source_version="same-version",
        object_name="activity.fit",
        content_type="application/fits",
        size_bytes=10,
        status="completed",
    )
    db = FakeSession([first, second, checkpoint])
    source_object = DriveArchiveObject(
        object_id="same-object",
        name="activity.fit",
        mime_type="application/fits",
        version="same-version",
        modified_time=None,
        size_bytes=10,
    )
    monkeypatch.setattr(
        archive_import_jobs,
        "_drive_client",
        lambda: SimpleNamespace(
            list_supported_objects=lambda _folder: [source_object],
            download=lambda _object: b"fit-bytes",
        ),
    )
    monkeypatch.setattr(
        archive_import_jobs,
        "ingest_archive_object",
        lambda **_kwargs: {"activity_count": 1},
    )
    job = archive_import_jobs.create_drive_import_job(db, second, folder_id="folder-two")

    result = archive_import_jobs.process_archive_import_job(db, job)

    assert result["objects_imported"] == 1
    checkpoints = [item for item in db.items if isinstance(item, ArchiveImportObject)]
    assert {item.user_id for item in checkpoints} == {first.id, second.id}


def test_status_lookup_hides_another_athletes_job():
    owner = _user("owner@example.com")
    intruder = _user("intruder@example.com")
    job = ArchiveImportJob(
        id=uuid.uuid4(),
        user_id=owner.id,
        provider="garmin_archive",
        source_type="google_drive",
        source_locator="folder-one",
        status="queued",
        filename="Google Drive Garmin archive",
        content_type="application/vnd.google-apps.folder",
        size_bytes=0,
        storage_backend="google_drive",
        storage_key=f"google-drive/{owner.id}/job",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db = FakeSession([job])

    with pytest.raises(HTTPException) as error:
        archive_import_jobs.get_archive_import_job_status(db, intruder, job.id)

    assert error.value.status_code == 404


def test_archive_formats_share_a_canonical_activity_fingerprint():
    """JSON and FIT representations of one workout must not create two activities."""
    athlete = _user()
    first_run = IngestRun(id=uuid.uuid4(), user_id=athlete.id, provider="garmin_archive")
    second_run = IngestRun(id=uuid.uuid4(), user_id=athlete.id, provider="garmin_archive")
    db = FakeSession([athlete, first_run, second_run])
    shared = {
        "startTimeGmt": "2026-09-09T22:49:13+00:00",
        "duration": 3600,
        "distance": 10000,
        "activityType": "running",
        "canonicalFingerprint": "canonical-workout-hash",
    }

    persist_activity_summaries(
        db,
        athlete,
        first_run,
        [{**shared, "activityId": "garmin-summary-123"}],
        provider="garmin_archive",
    )
    persist_activity_summaries(
        db,
        athlete,
        second_run,
        [{**shared, "activityId": "drive-fit-object-456"}],
        provider="garmin_archive",
    )

    activities = [item for item in db.items if isinstance(item, Activity)]
    assert len(activities) == 1
    assert activities[0].user_id == athlete.id
    assert activities[0].fingerprint_hash == "canonical-workout-hash"


def test_summarized_drive_json_is_normalized_with_provenance():
    athlete = _user()
    db = FakeSession([athlete])
    source = DriveArchiveObject(
        object_id="json-object",
        name="runner_1_summarizedActivities.json",
        mime_type="application/json",
        version="json-md5",
        modified_time="2026-09-03T12:32:49Z",
        size_bytes=100,
    )
    content = json.dumps(
        [
            {
                "summarizedActivitiesExport": [
                    {
                        "activityId": 123,
                        "name": "Morning Run",
                        "sportType": "RUNNING",
                        "beginTimestamp": 1788976800000,
                        "duration": 3600000,
                        "distance": 1000000,
                    }
                ]
            }
        ]
    ).encode()

    result = ingest_archive_object(db=db, user=athlete, source_object=source, content=content)

    activity = next(item for item in db.items if isinstance(item, Activity))
    assert result["activity_count"] == 1
    assert activity.user_id == athlete.id
    assert activity.distance_m == 10000
    assert activity.metadata_json["source_object_id"] == "json-object"
    assert activity.metadata_json["source_object_version"] == "json-md5"
