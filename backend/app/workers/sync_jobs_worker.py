"""Standalone worker loop for queued sync jobs."""

from __future__ import annotations

import logging
import os
import time

from app.db import SESSION_FACTORY
from app.services.sync_jobs import process_pending_sync_jobs


logger = logging.getLogger("sync.worker")


def run_once() -> dict[str, int]:
    """Process the currently queued sync jobs one time."""
    session = SESSION_FACTORY()
    try:
        return process_pending_sync_jobs(session)
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
        logger.info("sync worker poll complete", extra=summary)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
