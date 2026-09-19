"""Read-only flow checks must agree with the server's actual capabilities."""

from copy import deepcopy
from types import SimpleNamespace
import uuid

from app.services.archive_capabilities import archive_capabilities
from app.models import DossierJob
from app.services.dossiers import dossier_eligibility, job_payload
from test_dossiers import FakeSession, journey_snapshot


def test_drive_requires_both_athlete_folder_and_service_credentials():
    athlete = SimpleNamespace(email="Runner@Example.com")
    settings = SimpleNamespace(
        google_drive_archive_sources_json='{"runner@example.com": "folder-one"}',
        google_drive_service_account_json=None,
        google_drive_service_account_file=None,
        archive_import_storage_backend="filesystem",
        archive_import_filesystem_root="/tmp/archive-test",
        archive_import_gcs_bucket=None,
    )
    unavailable = archive_capabilities(athlete, settings=settings)
    assert unavailable["drive"]["available"] is False
    assert "credentials" in unavailable["drive"]["reason"].lower()
    settings.google_drive_service_account_json = '{"client_email":"reader@example.com"}'
    assert archive_capabilities(athlete, settings=settings)["drive"]["available"] is False
    settings.google_drive_service_account_json = (
        '{"client_email":"reader@example.com","private_key":"key",'
        '"token_uri":"https://oauth2.googleapis.com/token"}'
    )
    assert archive_capabilities(athlete, settings=settings)["drive"]["available"] is True
    settings.google_drive_archive_sources_json = "{}"
    assert archive_capabilities(athlete, settings=settings)["drive"]["available"] is False


def test_dossier_eligibility_uses_current_selected_canonical_window():
    athlete_id = uuid.uuid4()
    snapshot = journey_snapshot(activity_count=0)

    def current_journey(**_kwargs):
        return deepcopy(snapshot)

    empty = dossier_eligibility(
        FakeSession(), athlete_id, window="90d", sport="run", goal="marathon",
        journey_builder=current_journey,
    )
    assert empty["eligible"] is False
    snapshot["totals"]["activity_count"] = 106
    ready = dossier_eligibility(
        FakeSession(), athlete_id, window="90d", sport="run", goal="marathon",
        journey_builder=current_journey,
    )
    assert ready["eligible"] is True
    assert ready["activity_count"] == 106


def test_job_payload_discloses_the_frozen_activity_count_for_stale_state_checks():
    job = DossierJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="insufficient_data",
        snapshot_hash="empty",
        request_json={
            "filters": {"window": "90d", "sport": "all", "goal": "all"},
            "snapshot": {"totals": {"activity_count": 0}},
        },
    )
    assert job_payload(job)["activity_count"] == 0
