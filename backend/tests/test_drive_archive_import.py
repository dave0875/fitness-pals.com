"""Drive archive source, checkpoint, dedupe, and ownership tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
    Null,
)
from starlette.requests import Request

from app.models import (
    Activity,
    ActivityTrainingEvidence,
    ArchiveImportJob,
    ArchiveImportObject,
    IngestRun,
    ProviderApp,
    User,
    UserProviderToken,
)
from app.services import archive_import_jobs, garmin_archive_import
from app.routes import archive_imports as archive_routes
from app.services.garmin.activity import persist_activity_summaries
from app.services.garmin_archive_import import NoSupportedGarminActivities, ingest_archive_object
from app.services.google_drive_archive import (
    DRIVE_READONLY_SCOPE,
    DriveArchiveObject,
    GoogleDriveArchiveClient,
    configured_folder_for_user,
    google_drive_authorization_url,
    require_matching_google_account,
)
from app.utils.security import encrypt_token


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

    def order_by(self, *_criteria):
        return self

    @staticmethod
    def _value(side, item):
        if isinstance(side, Null):
            return None
        if isinstance(side, BindParameter):
            return side.value
        key = getattr(side, "key", None) or getattr(side, "name", None)
        return getattr(item, key) if key and hasattr(item, key) else side

    def _matches(self, condition, item):
        if isinstance(condition, BooleanClauseList):
            clauses = [self._matches(part, item) for part in condition.clauses]
            return all(clauses) if condition.operator is operators.and_ else any(clauses)
        if isinstance(condition, BinaryExpression):
            left = self._value(condition.left, item)
            right = self._value(condition.right, item)
            if condition.operator is operators.is_:
                return left is right
            return condition.operator(left, right)
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


def _oauth_app():
    return ProviderApp(
        id=uuid.uuid4(),
        provider="google_drive",
        display_name="Google Drive",
        client_id="drive-client-id",
        client_secret_encrypted=encrypt_token("drive-client-secret"),
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        redirect_uri="https://fitness-pals.com/api/archive-imports/google-drive/callback",
        scopes=f"openid email {DRIVE_READONLY_SCOPE}",
    )


def test_drive_authorization_requests_read_only_offline_access_for_signed_in_email():
    db = FakeSession([_oauth_app()])
    url = google_drive_authorization_url(
        db,
        state="csrf-state",
        login_hint="Runner@Example.com",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["drive-client-id"]
    assert query["redirect_uri"] == [
        "https://fitness-pals.com/api/archive-imports/google-drive/callback"
    ]
    assert query["state"] == ["csrf-state"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["login_hint"] == ["runner@example.com"]
    assert DRIVE_READONLY_SCOPE in query["scope"][0].split()


def test_drive_authorization_rejects_a_different_or_unverified_google_account():
    user = _user("runner@example.com")

    assert require_matching_google_account(
        user, {"email": "RUNNER@example.com", "verified_email": True, "id": "google-123"}
    ) == ("runner@example.com", "google-123")

    with pytest.raises(HTTPException, match="same Google account"):
        require_matching_google_account(
            user, {"email": "other@example.com", "verified_email": True, "id": "google-456"}
        )
    with pytest.raises(HTTPException, match="verified email"):
        require_matching_google_account(
            user, {"email": "runner@example.com", "verified_email": False, "id": "google-123"}
        )


def test_archive_capabilities_offer_authorization_then_enable_the_user_grant(
    monkeypatch,
):
    athlete = _user()
    app = _oauth_app()
    monkeypatch.setattr(
        archive_routes,
        "archive_capabilities",
        lambda _user: {
            "drive": {"available": False, "reason": "No private folder."},
            "upload": {"available": True, "reason": None},
        },
    )

    disconnected = archive_routes.capabilities(user=athlete, db=FakeSession([app]))

    assert disconnected["drive"]["authorization_available"] is True
    assert disconnected["drive"]["connected"] is False
    assert disconnected["drive"]["available"] is False
    assert "Authorize Google Drive" in disconnected["drive"]["reason"]

    token = UserProviderToken(
        id=uuid.uuid4(),
        user_id=athlete.id,
        tenant_id=None,
        provider="google_drive",
        provider_user_id="google-user",
        access_token_encrypted=b"encrypted",
        refresh_token_encrypted=b"encrypted-refresh",
        scope=DRIVE_READONLY_SCOPE,
        metadata_json={"email": athlete.email},
    )
    connected = archive_routes.capabilities(user=athlete, db=FakeSession([app, token]))

    assert connected["drive"]["connected"] is True
    assert connected["drive"]["available"] is True
    assert connected["drive"]["account_email"] == athlete.email
    assert connected["drive"]["reason"] is None


def _request_with_session(session):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/archive-imports/google-drive/callback",
            "headers": [],
            "session": session,
        }
    )


def test_drive_callback_requires_state_and_persists_the_matching_grant(monkeypatch):
    athlete = _user()
    session = {
        archive_routes.DRIVE_OAUTH_SESSION_KEY: {
            "state": "expected-state",
            "user_id": str(athlete.id),
            "next": "/import/garmin-archive?drive=connected",
        }
    }
    db = FakeSession([athlete])
    saved = []
    token = {
        "access_token": "google-access",
        "refresh_token": "google-refresh",
        "scope": f"openid email {DRIVE_READONLY_SCOPE}",
    }
    profile = {
        "email": athlete.email,
        "email_verified": True,
        "sub": "google-123",
    }
    monkeypatch.setattr(
        archive_routes,
        "exchange_google_drive_code",
        lambda session_db, code: token,
    )
    monkeypatch.setattr(archive_routes, "fetch_google_profile", lambda access: profile)
    monkeypatch.setattr(
        archive_routes,
        "save_google_drive_grant",
        lambda session_db, user, payload, identity: saved.append(
            (session_db, user, payload, identity)
        ),
    )

    response = archive_routes.google_drive_callback(
        _request_with_session(session),
        state="expected-state",
        code="authorization-code",
        user=athlete,
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/import/garmin-archive?drive=connected"
    assert saved == [(db, athlete, token, profile)]
    assert archive_routes.DRIVE_OAUTH_SESSION_KEY not in session


def test_drive_callback_rejects_csrf_state_before_token_exchange(monkeypatch):
    athlete = _user()
    exchanged = []
    monkeypatch.setattr(
        archive_routes,
        "exchange_google_drive_code",
        lambda session_db, code: exchanged.append(code),
    )

    with pytest.raises(HTTPException, match="Invalid Google Drive authorization state"):
        archive_routes.google_drive_callback(
            _request_with_session(
                {
                    archive_routes.DRIVE_OAUTH_SESSION_KEY: {
                        "state": "expected-state",
                        "user_id": str(athlete.id),
                    }
                }
            ),
            state="attacker-state",
            code="authorization-code",
            user=athlete,
            db=FakeSession([athlete]),
        )

    assert exchanged == []


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


def test_archive_job_persists_live_progress_after_each_checkpoint(monkeypatch):
    athlete = _user()
    db = FakeSession([athlete])
    objects = [
        DriveArchiveObject(
            object_id=f"drive-file-{index}",
            name=f"activity-{index}.fit",
            mime_type="application/fits",
            version=f"version-{index}",
            modified_time=None,
            size_bytes=10,
        )
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        archive_import_jobs,
        "_drive_client",
        lambda: SimpleNamespace(
            list_supported_objects=lambda _folder: objects,
            download=lambda _object: b"fit-bytes",
        ),
    )

    observed = []

    def fake_process(_db, job, source, _content_loader):
        observed.append((source.object_id, dict(job.result_json or {})))
        return "imported", 1

    monkeypatch.setattr(archive_import_jobs, "_process_object", fake_process)
    job = archive_import_jobs.create_drive_import_job(
        db, athlete, folder_id="folder-one"
    )

    result = archive_import_jobs.process_archive_import_job(db, job)

    assert observed[0][1] == {
        "objects_total": 2,
        "objects_processed": 0,
        "objects_imported": 0,
        "objects_skipped": 0,
        "objects_failed": 0,
        "activities": 0,
    }
    assert observed[1][1]["objects_processed"] == 1
    assert observed[1][1]["objects_imported"] == 1
    assert observed[1][1]["activities"] == 1
    assert result["objects_total"] == 2
    assert result["objects_processed"] == 2
    assert result["objects_imported"] == 2
    assert result["activities"] == 2
    assert job.result_json == result
    assert job.status == "completed"


def test_user_authorized_drive_job_uses_athletes_encrypted_grant(monkeypatch):
    athlete = _user()
    token = UserProviderToken(
        id=uuid.uuid4(),
        user_id=athlete.id,
        tenant_id=None,
        provider="google_drive",
        provider_user_id="google-user",
        access_token_encrypted=b"encrypted",
        refresh_token_encrypted=b"encrypted-refresh",
        scope=DRIVE_READONLY_SCOPE,
        metadata_json={"email": athlete.email},
    )
    db = FakeSession([athlete, token])
    fake_drive = SimpleNamespace(list_supported_objects=lambda folder: [], download=lambda item: b"")
    captured = []
    monkeypatch.setattr(
        archive_import_jobs.GoogleDriveArchiveClient,
        "for_user",
        lambda session, user: captured.append((session, user)) or fake_drive,
    )

    job = archive_import_jobs.create_drive_import_job(
        db,
        athlete,
        folder_id="root",
        authorization="user_oauth",
    )
    result = archive_import_jobs.process_archive_import_job(db, job)

    assert result["objects_imported"] == 0
    assert captured == [(db, athlete)]
    assert job.source_metadata_json == {
        "folder_id": "root",
        "authorization": "user_oauth",
    }


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
    evidence = [
        item for item in db.items if isinstance(item, ActivityTrainingEvidence)
    ]
    assert len(activities) == 1
    assert len(evidence) == 1
    assert activities[0].user_id == athlete.id
    assert activities[0].fingerprint_hash == "canonical-workout-hash"
    assert evidence[0].activity_id == activities[0].id
    assert evidence[0].modality == "running"


def test_sparse_replay_does_not_reassign_rich_metric_provenance():
    athlete = _user()
    fit_run = IngestRun(id=uuid.uuid4(), user_id=athlete.id, provider="garmin_archive")
    json_run = IngestRun(id=uuid.uuid4(), user_id=athlete.id, provider="garmin_archive")
    db = FakeSession([athlete, fit_run, json_run])
    base = {
        "startTimeGmt": "2026-09-09T22:49:13+00:00",
        "duration": 3600,
        "distance": 30000,
        "activityType": "cycling",
        "canonicalFingerprint": "same-ride",
    }

    persist_activity_summaries(
        db,
        athlete,
        fit_run,
        [{
            **base,
            "activityId": "fit-ride",
            "sourceObjectId": "fit-object",
            "sourceObjectName": "ride.fit",
            "sourceObjectVersion": "fit-v1",
            "sourceContentHash": "fit-hash",
            "trainingEvidence": {
                "provider_sport": "cycling",
                "avg_heart_rate": 146,
                "avg_power": 211,
            },
        }],
        provider="garmin_archive",
    )
    persist_activity_summaries(
        db,
        athlete,
        json_run,
        [{
            **base,
            "activityId": "json-ride",
            "sourceObjectId": "json-object",
            "sourceObjectName": "summary.json",
            "sourceObjectVersion": "json-v1",
            "sourceContentHash": "json-hash",
        }],
        provider="garmin_archive",
    )

    rows = [
        item for item in db.items if isinstance(item, ActivityTrainingEvidence)
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row.avg_heart_rate == 146
    assert row.avg_power == 211
    assert row.field_provenance_json["avg_power"] == {
        "provider": "garmin_archive",
        "object_id": "fit-object",
        "object_name": "ride.fit",
        "object_version": "fit-v1",
        "content_hash": "fit-hash",
    }
    assert "avg_power" in row.observed_fields


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


def test_summarized_json_missing_distance_and_duration_stay_unknown():
    normalized = garmin_archive_import._normalize_summary(
        {
            "activityId": 456,
            "name": "Strength",
            "sportType": "strength_training",
            "beginTimestamp": 1788976800000,
        }
    )

    assert normalized["distance"] is None
    assert normalized["duration"] is None


def test_root_oauth_drive_scope_only_selects_activity_sources():
    activity_fit = {"name": "2026-09-20-07-52-49.fit", "mimeType": "application/fits"}
    exported_fit = {"name": "24428629583_ACTIVITY.fit", "mimeType": "application/fits"}
    monitor_fit = {"name": "monitor.fit", "mimeType": "application/fits"}
    uploaded_zip = {"name": "UploadedFiles_0-_Part7.zip", "mimeType": "application/zip"}
    training_zip = {
        "name": "runner_PrimaryTrainingBackup_Part1.zip",
        "mimeType": "application/zip",
    }
    summaries = {
        "name": "runner_1_summarizedActivities.json",
        "mimeType": "application/json",
    }

    assert GoogleDriveArchiveClient._supported(
        activity_fit, path=("Fenix8_Backup", "Activity"), root_scoped=True
    )
    assert GoogleDriveArchiveClient._supported(
        exported_fit, path=("somewhere",), root_scoped=True
    )
    assert not GoogleDriveArchiveClient._supported(
        monitor_fit, path=("Fenix8_Backup", "Monitor"), root_scoped=True
    )
    assert GoogleDriveArchiveClient._supported(
        uploaded_zip,
        path=("GarminDataExport.zip", "DI_CONNECT", "DI-Connect-Uploaded-Files"),
        root_scoped=True,
    )
    assert not GoogleDriveArchiveClient._supported(
        training_zip,
        path=("GarminDataExport.zip", "DI_CONNECT", "DI-Connect-Fitness"),
        root_scoped=True,
    )
    assert GoogleDriveArchiveClient._supported(
        summaries,
        path=("GarminDataExport.zip", "DI_CONNECT", "DI-Connect-Fitness"),
        root_scoped=True,
    )


def test_official_garmin_fit_sdk_session_messages_are_normalized(monkeypatch):
    source = DriveArchiveObject(
        object_id="fit-object",
        name="2026-09-20-07-52-49.fit",
        mime_type="application/fits",
        version="v1",
        modified_time=None,
        size_bytes=10,
    )

    def fake_decode(content: bytes):
        assert content == b"fit-bytes"
        return (
            {
                "session_mesgs": [
                    {
                        "start_time": datetime(
                            2026, 9, 20, 11, 52, 49, tzinfo=timezone.utc
                        ),
                        "sport": "cycling",
                        "sub_sport": "indoor_cycling",
                        "total_distance": 30000.0,
                        "total_timer_time": 4500.0,
                        "total_elapsed_time": 4700.0,
                        "avg_heart_rate": 146,
                        "max_heart_rate": 172,
                        "avg_power": 211,
                        "max_power": 540,
                        "normalized_power": 228,
                        "total_calories": 820,
                        "first_lap_index": 0,
                        "num_laps": 1,
                    }
                ],
                "lap_mesgs": [
                    {
                        "start_time": datetime(
                            2026, 9, 20, 11, 52, 49, tzinfo=timezone.utc
                        ),
                        "total_timer_time": 600.0,
                        "avg_heart_rate": 140,
                        "avg_power": 200,
                        "intensity": "active",
                    }
                ],
            },
            {},
        )

    monkeypatch.setattr(garmin_archive_import, "decode_fit_bytes", fake_decode)

    activities = garmin_archive_import._fit_activities(b"fit-bytes", source)

    assert len(activities) == 1
    assert activities[0]["activityType"] == "cycling"
    assert activities[0]["subSport"] == "indoor_cycling"
    assert activities[0]["distance"] == 30000.0
    assert activities[0]["duration"] == 4500.0
    assert activities[0]["startTimeGmt"] == "2026-09-20T11:52:49+00:00"
    training = activities[0]["trainingEvidence"]
    assert training["avg_heart_rate"] == 146
    assert training["max_heart_rate"] == 172
    assert training["avg_power"] == 211
    assert training["max_power"] == 540
    assert training["normalized_power"] == 228
    assert training["calories"] == 820
    assert training["structure"]["laps"][0]["timer_seconds"] == 600.0


def test_strength_fit_preserves_sets_without_distance_semantics(monkeypatch):
    source = DriveArchiveObject(
        object_id="strength-fit",
        name="2026-09-23-strength.fit",
        mime_type="application/fits",
        version="v2",
        modified_time=None,
        size_bytes=10,
    )

    monkeypatch.setattr(
        garmin_archive_import,
        "decode_fit_bytes",
        lambda _content: (
            {
                "session_mesgs": [
                    {
                        "start_time": datetime(
                            2026, 9, 23, 22, 0, tzinfo=timezone.utc
                        ),
                        "sport": "training",
                        "sub_sport": "strength_training",
                        "total_timer_time": 2700.0,
                        "avg_heart_rate": 128,
                    }
                ],
                "set_mesgs": [
                    {
                        "timestamp": datetime(
                            2026, 9, 23, 22, 5, tzinfo=timezone.utc
                        ),
                        "duration": 42.0,
                        "repetitions": 10,
                        "weight": 22.5,
                        "set_type": "active",
                        "category": "squat",
                    }
                ],
            },
            {},
        ),
    )

    activities = garmin_archive_import._fit_activities(b"strength", source)

    assert len(activities) == 1
    assert activities[0]["subSport"] == "strength_training"
    assert activities[0]["distance"] is None
    evidence = activities[0]["trainingEvidence"]
    assert evidence["avg_heart_rate"] == 128
    assert evidence["avg_power"] is None
    assert evidence["structure"]["sets"][0] == {
        "index": 0,
        "timestamp": "2026-09-23T22:05:00+00:00",
        "duration_seconds": 42.0,
        "repetitions": 10.0,
        "weight_kg": 22.5,
        "set_type": "active",
        "category": "squat",
        "exercise_name": None,
    }


def test_no_activity_drive_object_is_durable_skip(monkeypatch):
    athlete = _user()
    db = FakeSession([athlete])
    source_object = DriveArchiveObject(
        object_id="non-activity-fit",
        name="monitor.fit",
        mime_type="application/fits",
        version="v1",
        modified_time=None,
        size_bytes=10,
    )
    downloads = []
    fake_drive = SimpleNamespace(
        list_supported_objects=lambda _folder_id: [source_object],
        download=lambda _object: downloads.append(_object.object_id) or b"fit-bytes",
    )
    monkeypatch.setattr(archive_import_jobs, "_drive_client", lambda: fake_drive)

    def no_activity(**_kwargs):
        raise NoSupportedGarminActivities("no supported Garmin activities")

    monkeypatch.setattr(archive_import_jobs, "ingest_archive_object", no_activity)

    first_job = archive_import_jobs.create_drive_import_job(
        db, athlete, folder_id="folder-one"
    )
    first = archive_import_jobs.process_archive_import_job(db, first_job)

    replay = ArchiveImportJob(
        user_id=athlete.id,
        provider="garmin_archive",
        source_type="google_drive",
        source_locator="folder-one",
        source_metadata_json={
            "folder_id": "folder-one",
            "authorization": "service_account",
        },
        status="queued",
        filename="Google Drive Garmin archive",
        content_type="application/vnd.google-apps.folder",
        size_bytes=0,
        storage_backend="google_drive",
        storage_key=f"google-drive/{athlete.id}/replay-no-activity",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(replay)
    db.commit()
    second = archive_import_jobs.process_archive_import_job(db, replay)

    checkpoint = next(item for item in db.items if isinstance(item, ArchiveImportObject))
    assert first["objects_skipped"] == 1
    assert first["objects_failed"] == 0
    assert first_job.status == "completed"
    assert checkpoint.status == "skipped"
    assert checkpoint.result_json == {"reason": "no_supported_activities"}
    assert second["objects_skipped"] == 1
    assert second["objects_failed"] == 0
    assert replay.status == "completed"
    assert downloads == ["non-activity-fit"]
