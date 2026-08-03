"""Standalone worker loop for queued sync and dossier jobs."""

from __future__ import annotations

import logging
import os
import time

from app.db import SESSION_FACTORY
from app.services.sync_jobs import process_pending_sync_jobs
from app.services.dossiers import process_pending_dossier_jobs


logger = logging.getLogger("sync.worker")


def run_once() -> dict[str, int]:
    """Process the currently queued sync jobs one time."""
    session = SESSION_FACTORY()
    try:
        sync_summary = process_pending_sync_jobs(session)
        dossier_summary = process_pending_dossier_jobs(session)
        return {
            **{f"sync_{key}": value for key, value in sync_summary.items()},
            **{f"dossier_{key}": value for key, value in dossier_summary.items()},
        }
    finally:
        session.close()


def main() -> None:
    """Poll the sync job queue until the container stops."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    interval_seconds = int(os.environ.get("SYNC_WORKER_POLL_INTERVAL_SECONDS", "5"))
    while True:
        summary = run_once()
        logger.info("worker poll complete", extra=summary)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
