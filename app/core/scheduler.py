"""Process-wide APScheduler instance, started/stopped via main.py's
FastAPI lifespan.

Deliberately in-process (not a separate scheduler container), analogous to
the vb-fastapi-vue sister project's app/core/scheduler.py -- including its
pg_try_advisory_lock guard against duplicate job registration across
multiple Gunicorn worker processes. Under SQLite (Phase 1, always a single
dev process) that guard is a no-op; it only becomes active once Phase 2
(Postgres) runs multiple prod workers, exactly as in vb-api today.

Schritt 1 registers zero jobs on purpose -- real jobs land with their
respective domain slices (e.g. token/log cleanup, BookingStatus mail).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.database import engine

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Arbitrary fixed int64 key identifying "the osa-backend scheduler" for
# pg_try_advisory_lock. Any int64 works as long as it stays constant.
_SCHEDULER_LOCK_KEY = 8_872_502

# Held open for the process lifetime once acquired, so the advisory lock
# stays taken until this worker process exits (Postgres releases advisory
# locks automatically when the holding connection closes).
_scheduler_lock_conn: Connection | None = None


def _acquire_scheduler_lock() -> bool:
    """Ensure only one process runs the scheduler.

    SQLite (dev-only in Phase 1) never runs with multiple workers, so it
    skips the lock and always starts. Relevant once Phase 2 (Postgres) runs
    production with multiple Gunicorn workers.
    """
    global _scheduler_lock_conn  # noqa: PLW0603 -- lazy singleton, holds the advisory-lock connection open for process lifetime

    if engine.dialect.name != "postgresql":
        return True

    conn = engine.sync_engine.connect()
    acquired = bool(
        conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _SCHEDULER_LOCK_KEY},
        ).scalar()
    )
    if not acquired:
        conn.close()
        return False

    _scheduler_lock_conn = conn
    return True


def start_scheduler() -> None:
    if not _acquire_scheduler_lock():
        logger.info(
            "Scheduler lock held by another worker process -- skipping startup here."
        )
        return

    scheduler.start()
    logger.info("Scheduler started with %d job(s).", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler_lock_conn  # noqa: PLW0603 -- releases the singleton set up in _acquire_scheduler_lock()

    if scheduler.running:
        scheduler.shutdown(wait=False)

    if _scheduler_lock_conn is not None:
        _scheduler_lock_conn.close()
        _scheduler_lock_conn = None

    logger.info("Scheduler stopped.")
