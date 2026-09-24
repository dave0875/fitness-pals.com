"""Tests for the bounded whole-training FIT evidence backfill."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import backfill_training_evidence


def test_discovery_is_deterministic_bounded_and_fit_only(tmp_path: Path):
    (tmp_path / "b.fit").write_bytes(b"b")
    (tmp_path / "a.FIT").write_bytes(b"a")
    (tmp_path / "ignore.json").write_text("{}")

    files = backfill_training_evidence.discover_fit_files(tmp_path, 1)

    assert [path.name for path in files] == ["a.FIT"]


def test_checkpoint_round_trip_is_replay_safe(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    state = {
        "completed": {"hash-1": {"path": "one.fit", "activity_count": 1}},
        "failed": {},
    }

    backfill_training_evidence.write_checkpoint(path, state)

    assert backfill_training_evidence.load_checkpoint(path) == state
    assert json.loads(path.read_text()) == state


def test_dry_run_reports_decode_failures_without_mutation(tmp_path: Path, monkeypatch):
    good = tmp_path / "good.fit"
    bad = tmp_path / "bad.fit"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")

    def fake_inspect(path):
        if path.name == "bad.fit":
            raise ValueError("bad FIT")
        return {
            "path": str(path),
            "content_hash": "hash",
            "activity_count": 2,
            "observed_training_fields": ["avg_heart_rate"],
        }

    monkeypatch.setattr(backfill_training_evidence, "inspect_file", fake_inspect)

    report = backfill_training_evidence.dry_run(tmp_path, 10)

    assert report["mode"] == "dry_run"
    assert report["files_selected"] == 2
    assert report["activities_decoded"] == 2
    assert report["failures"] == [
        {"path": str(bad), "error": "ValueError"}
    ]
