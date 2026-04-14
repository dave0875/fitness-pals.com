"""Tests for storage-backed Garmin export import jobs."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, BindParameter


os.environ.setdefault("RUNTRAINER_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault(
    "RUNTRAINER_FERNET_KEY", "RUroXk_5cPR0yW9SKG3Y4995FbGgRsdrucrb7Sxl67s="
)
os.environ.setdefault("RUNTRAINER_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_ID", "test-google-client")
os.environ.setdefault("RUNTRAINER_GOOGLE_CLIENT_SECRET", "test-google-secret")
os.environ.setdefault(
    "RUNTRAINER_GOOGLE_REDIRECT_URI", "https://example.com/auth/google/callback"
)

from app import deps, main  # noqa: E402  pylint: disable=wrong-import-position
from app.models import User
from app.services import archive_import_jobs  # noqa: E402  pylint: disable=wrong-import-position


class FakeQuery:
    """Subset of SQLAlchemy query behavior needed for archive import tests."""

    def __init__(self, data):
        self.data = list(data)

    def filter(self, *conditions, **_kwargs):
        filtered = []
        for item in self.data:
            if all(self._matches(cond, item) for cond in conditions):
                filtered.append(item)
        return FakeQuery(filtered)

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.data)

    def first(self):
        return self.data[0] if self.data else None

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
            return condition.operator(left, right)
        return True


class FakeSession:
    """Minimal session stub for route-level archive import tests."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def add(self, obj):
        self.items.append(obj)

    def commit(self):
        for obj in self.items:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        return obj

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def get(self, model, object_id):
        for item in self.items:
            if isinstance(item, model) and getattr(item, "id", None) == object_id:
                return item
        return None


def _fake_user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="runner@example.com",
        name="Runner Example",
    )


def test_start_endpoint_returns_signed_upload_plan(monkeypatch):
    """Starting a large Garmin import should return a signed upload target plus job urls."""
    fake_user = _fake_user()
    fake_job_id = uuid.uuid4()

    monkeypatch.setattr(
        archive_import_jobs,
        "create_archive_import_job",
        lambda db, user, filename, content_type, size_bytes: {
            "job_id": str(fake_job_id),
            "status": "upload_pending",
            "upload": {
                "url": "https://storage.example.test/upload",
                "method": "PUT",
                "headers": {"Content-Type": "application/zip"},
            },
            "complete_url": f"/api/dossiers/import/garmin-export/{fake_job_id}/complete",
            "status_url": f"/api/dossiers/import/garmin-export/{fake_job_id}",
        },
    )

    client = TestClient(main.app)
    main.app.dependency_overrides[deps.get_db] = lambda: FakeSession()
    main.app.dependency_overrides[deps.get_current_user] = lambda: fake_user
    try:
        response = client.post(
            "/api/dossiers/import/garmin-export/start",
            json={
                "filename": "Garmin Export.zip",
                "content_type": "application/zip",
                "size_bytes": 451_000_000,
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "upload_pending"
    assert body["upload"]["method"] == "PUT"
    assert body["upload"]["url"] == "https://storage.example.test/upload"
    assert body["complete_url"].endswith("/complete")
    assert body["status_url"].endswith(str(fake_job_id))


def test_complete_endpoint_marks_job_queued_for_worker(monkeypatch):
    """Completing an uploaded archive should queue it for worker ingestion."""
    fake_user = _fake_user()
    fake_job_id = uuid.uuid4()

    monkeypatch.setattr(
        archive_import_jobs,
        "complete_archive_import_job",
        lambda db, user, job_id: {
            "job_id": str(job_id),
            "status": "queued",
        },
    )

    client = TestClient(main.app)
    main.app.dependency_overrides[deps.get_db] = lambda: FakeSession()
    main.app.dependency_overrides[deps.get_current_user] = lambda: fake_user
    try:
        response = client.post(f"/api/dossiers/import/garmin-export/{fake_job_id}/complete")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"job_id": str(fake_job_id), "status": "queued"}


def test_status_endpoint_surfaces_completed_dossier_link(monkeypatch):
    """Polling import status should eventually reveal the published dossier URL."""
    fake_user = _fake_user()
    fake_job_id = uuid.uuid4()

    monkeypatch.setattr(
        archive_import_jobs,
        "get_archive_import_job_status",
        lambda db, user, job_id: {
            "job_id": str(job_id),
            "status": "completed",
            "dossier_url": "/coach-dossiers/runner-example-garmin-archive-dossier",
            "activity_count": 2920,
        },
    )

    client = TestClient(main.app)
    main.app.dependency_overrides[deps.get_db] = lambda: FakeSession()
    main.app.dependency_overrides[deps.get_current_user] = lambda: fake_user
    try:
        response = client.get(f"/api/dossiers/import/garmin-export/{fake_job_id}")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["dossier_url"].endswith("runner-example-garmin-archive-dossier")


def test_worker_processes_queued_archive_job_and_publishes_result(monkeypatch):
    """The worker layer should turn a queued uploaded archive into a completed dossier result."""
    fake_user = User(
        id=uuid.uuid4(),
        email="runner@example.com",
        name="Runner Example",
        created_at=datetime.now(timezone.utc),
        last_login_at=datetime.now(timezone.utc),
    )
    db = FakeSession([fake_user])

    monkeypatch.setattr(
        archive_import_jobs,
        "_get_storage_client",
        lambda: SimpleNamespace(
            storage_backend="test",
            create_upload_plan=lambda job: SimpleNamespace(
                url=f"https://storage.example.test/{job.id}",
                method="PUT",
                headers={"Content-Type": "application/zip"},
                expires_at=datetime.now(timezone.utc),
            ),
            object_exists=lambda job: True,
            read_bytes=lambda job: b"zip-bytes",
            write_bytes=lambda job, content: None,
        ),
    )

    create_result = archive_import_jobs.create_archive_import_job(
        db,
        fake_user,
        filename="Garmin Export.zip",
        content_type="application/zip",
        size_bytes=451_000_000,
    )
    job_id = uuid.UUID(create_result["job_id"])
    monkeypatch.setattr(
        archive_import_jobs,
        "import_garmin_export_archive",
        lambda *, db, user, filename, archive_bytes: {
            "status": "imported",
            "activity_count": 2920,
            "dossier_slug": "runner-example-garmin-archive-dossier",
            "dossier_url": "/coach-dossiers/runner-example-garmin-archive-dossier",
            "athlete_name": "Runner Example",
        },
    )

    archive_import_jobs.complete_archive_import_job(db, fake_user, job_id)
    summary = archive_import_jobs.process_pending_archive_import_jobs(db)
    status = archive_import_jobs.get_archive_import_job_status(db, fake_user, job_id)

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert status["status"] == "completed"
    assert status["dossier_url"].endswith("runner-example-garmin-archive-dossier")
