"""Redacted aggregate diagnostics for failed production Drive archive imports."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from app.db import SESSION_FACTORY
from app.models import ArchiveImportJob, ArchiveImportObject


_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _normalized_message(message: str, object_name: str | None = None) -> str:
    value = message or "<empty>"
    if object_name:
        value = value.replace(object_name, "<object>")
    value = _UUID_RE.sub("<uuid>", value)
    value = _EMAIL_RE.sub("<email>", value)
    return value[:600]


def _file_class(obj: ArchiveImportObject) -> str:
    suffix = Path(str(obj.object_name or "")).suffix.lower() or "<none>"
    return f"{suffix}|{obj.content_type or '<unknown>'}"


def _latest_failed_user_oauth_job(db: Any) -> ArchiveImportJob | None:
    jobs = (
        db.query(ArchiveImportJob)
        .filter(
            ArchiveImportJob.source_type == "google_drive",
            ArchiveImportJob.status == "failed",
        )
        .order_by(ArchiveImportJob.created_at.desc())
        .all()
    )
    return next(
        (
            job
            for job in jobs
            if (job.source_metadata_json or {}).get("authorization") == "user_oauth"
        ),
        None,
    )


def main() -> int:
    db = SESSION_FACTORY()
    try:
        job = _latest_failed_user_oauth_job(db)
        if job is None:
            print("DRIVE_DIAG no failed user_oauth Google Drive job found")
            return 1
        objects = (
            db.query(ArchiveImportObject)
            .filter(ArchiveImportObject.job_id == job.id)
            .all()
        )
        failed = [obj for obj in objects if obj.status == "failed"]
        signatures: Counter[tuple[str, str]] = Counter()
        classes: Counter[str] = Counter()
        for obj in failed:
            error = obj.error_json or {}
            error_type = str(error.get("type") or "<unknown>")
            message = _normalized_message(str(error.get("message") or ""), obj.object_name)
            signatures[(error_type, message)] += 1
            classes[_file_class(obj)] += 1

        result = job.result_json or {}
        print(
            "DRIVE_DIAG "
            f"job_status={job.status} checkpoints={len(objects)} failed={len(failed)} "
            f"objects_imported={int(result.get('objects_imported') or 0)} "
            f"objects_skipped={int(result.get('objects_skipped') or 0)} "
            f"objects_failed={int(result.get('objects_failed') or 0)}"
        )
        for file_class, count in classes.most_common(10):
            print(f"DRIVE_DIAG_CLASS count={count} class={file_class}")
        for (error_type, message), count in signatures.most_common(12):
            print(
                "DRIVE_DIAG_ERROR "
                f"count={count} type={error_type} message={message}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
