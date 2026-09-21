"""Contract tests for the production Google Drive acceptance gate."""

from __future__ import annotations

import pytest

from app.ops.prod_drive_acceptance import AcceptanceFailure, _assert_replay_idempotent


def test_replay_acceptance_requires_checkpointed_objects_and_stable_activity_count():
    _assert_replay_idempotent(
        {"objects_imported": 3, "objects_skipped": 2, "objects_failed": 0},
        {"objects_imported": 0, "objects_skipped": 5, "objects_failed": 0},
        activities_before_replay=100,
        activities_after_replay=100,
    )


def test_replay_acceptance_rejects_duplicate_activity_growth():
    with pytest.raises(AcceptanceFailure, match="activity count increased"):
        _assert_replay_idempotent(
            {"objects_imported": 2, "objects_skipped": 0, "objects_failed": 0},
            {"objects_imported": 0, "objects_skipped": 2, "objects_failed": 0},
            activities_before_replay=100,
            activities_after_replay=101,
        )


def test_replay_acceptance_rejects_reimported_objects():
    with pytest.raises(AcceptanceFailure, match="imported Drive objects"):
        _assert_replay_idempotent(
            {"objects_imported": 2, "objects_skipped": 0, "objects_failed": 0},
            {"objects_imported": 1, "objects_skipped": 1, "objects_failed": 0},
            activities_before_replay=100,
            activities_after_replay=100,
        )
