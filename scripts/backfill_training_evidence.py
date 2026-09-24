#!/usr/bin/env python3
"""Dry-run-first, checkpointed re-decoding of Garmin FIT activity evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.garmin_archive_import import _object_activities, ingest_archive_object
from app.services.google_drive_archive import DriveArchiveObject


def discover_fit_files(source_dir: Path, limit: int) -> list[Path]:
    """Return a deterministic, bounded FIT input set."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".fit"
    )[:limit]


def file_identity(path: Path) -> tuple[bytes, str]:
    content = path.read_bytes()
    return content, hashlib.sha256(content).hexdigest()


def source_object(path: Path, content_hash: str) -> DriveArchiveObject:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return DriveArchiveObject(
        object_id=f"training-backfill:{content_hash}",
        name=path.name,
        mime_type="application/fits",
        version=content_hash,
        modified_time=modified,
        size_bytes=stat.st_size,
    )


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"completed": {}, "failed": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    value.setdefault("completed", {})
    value.setdefault("failed", {})
    return value


def write_checkpoint(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def inspect_file(path: Path) -> dict[str, Any]:
    content, content_hash = file_identity(path)
    source = source_object(path, content_hash)
    activities = _object_activities(content, source)
    observed = set()
    for activity in activities:
        evidence = activity.get("trainingEvidence")
        if isinstance(evidence, dict):
            observed.update(
                key
                for key, value in evidence.items()
                if value not in (None, {}, [])
            )
    return {
        "path": str(path),
        "content_hash": content_hash,
        "activity_count": len(activities),
        "observed_training_fields": sorted(observed),
    }


def dry_run(source_dir: Path, limit: int) -> dict[str, Any]:
    files = discover_fit_files(source_dir, limit)
    inspected = []
    failures = []
    for path in files:
        try:
            inspected.append(inspect_file(path))
        except Exception as exc:  # pylint: disable=broad-except
            failures.append({"path": str(path), "error": type(exc).__name__})
    return {
        "mode": "dry_run",
        "files_selected": len(files),
        "activities_decoded": sum(item["activity_count"] for item in inspected),
        "files": inspected,
        "failures": failures,
    }


def _evidence_count(db, user_id: UUID) -> int:
    from app.models import Activity, ActivityTrainingEvidence

    return (
        db.query(ActivityTrainingEvidence)
        .join(Activity, Activity.id == ActivityTrainingEvidence.activity_id)
        .filter(Activity.user_id == user_id)
        .count()
    )


def apply(
    source_dir: Path,
    *,
    limit: int,
    expected_files: int,
    checkpoint_path: Path,
    email: str,
    user_id: UUID,
) -> dict[str, Any]:
    """Apply only after exact identity and bounded-input guards succeed."""
    from sqlalchemy import func
    from app.db import SESSION_FACTORY
    from app.models import User

    files = discover_fit_files(source_dir, limit)
    if len(files) != expected_files:
        raise ValueError(
            f"expected {expected_files} FIT files but selected {len(files)}"
        )
    checkpoint = load_checkpoint(checkpoint_path)
    db = SESSION_FACTORY()
    try:
        user = db.query(User).filter(func.lower(User.email) == email.lower()).one_or_none()
        if user is None or user.id != user_id:
            raise ValueError("account identity does not match email and user ID")
        before = _evidence_count(db, user_id)
        imported = 0
        skipped = 0
        failed = 0
        activities = 0
        for path in files:
            content, content_hash = file_identity(path)
            if content_hash in checkpoint["completed"]:
                skipped += 1
                continue
            try:
                result = ingest_archive_object(
                    db=db,
                    user=user,
                    source_object=source_object(path, content_hash),
                    content=content,
                )
                checkpoint["completed"][content_hash] = {
                    "path": str(path),
                    "activity_count": result["activity_count"],
                    "ingest_run_id": result["ingest_run_id"],
                }
                checkpoint["failed"].pop(content_hash, None)
                imported += 1
                activities += int(result["activity_count"])
            except Exception as exc:  # pylint: disable=broad-except
                checkpoint["failed"][content_hash] = {
                    "path": str(path),
                    "error": type(exc).__name__,
                }
                failed += 1
            write_checkpoint(checkpoint_path, checkpoint)
        after = _evidence_count(db, user_id)
        return {
            "mode": "apply",
            "files_selected": len(files),
            "files_imported": imported,
            "files_skipped": skipped,
            "files_failed": failed,
            "activities_decoded": activities,
            "training_evidence_before": before,
            "training_evidence_after": after,
            "training_evidence_delta": after - before,
            "checkpoint": str(checkpoint_path),
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-files", type=int)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--email")
    parser.add_argument("--user-id", type=UUID)
    args = parser.parse_args()

    if not args.apply:
        print(json.dumps(dry_run(args.source_dir, args.limit), indent=2, sort_keys=True))
        return 0

    if (
        args.expected_files is None
        or args.checkpoint is None
        or not args.email
        or args.user_id is None
    ):
        parser.error(
            "--apply requires --expected-files, --checkpoint, --email, and --user-id"
        )
    report = apply(
        args.source_dir,
        limit=args.limit,
        expected_files=args.expected_files,
        checkpoint_path=args.checkpoint,
        email=args.email,
        user_id=args.user_id,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["files_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
