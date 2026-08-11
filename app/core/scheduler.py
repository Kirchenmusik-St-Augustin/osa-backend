"""Process-wide APScheduler instance, started/stopped via main.py's
FastAPI lifespan.

Deliberately in-process (not a separate scheduler container), analogous to
the vb-fastapi-vue sister project's app/core/scheduler.py -- including its
pg_try_advisory_lock guard against duplicate job registration across
multiple Gunicorn worker processes. Under SQLite (Phase 1, always a single
dev process) that guard is a no-op; it only becomes active once Phase 2
(Postgres) runs multiple prod workers, exactly as in vb-api today.
"""

import logging
from zoneinfo import ZoneInfo

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobEvent,
    JobExecutionEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db.database import engine
from app.services.backup_jobs import job_backup_koofr
from app.services.booking_jobs import (
    notify_upcoming_booking_status,
    purge_stale_booking_requests,
)
from app.services.housekeeping_jobs import (
    purge_expired_password_reset_tokens,
    purge_old_request_logs,
)

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

    conn = engine.connect()
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


def _log_job_outcome(event: JobEvent | JobExecutionEvent) -> None:
    """Port of Legacy's ScheduledTask/Starting+Finished listeners --
    operational log lines only, no DB write, registered once for every job
    rather than duplicated per job function."""
    if event.code == EVENT_JOB_SUBMITTED:
        logger.info("Scheduled job starting: %s", event.job_id)
    elif event.code == EVENT_JOB_ERROR:
        logger.error("Scheduled job failed: %s", event.job_id)
    else:
        logger.info("Scheduled job finished: %s", event.job_id)


def start_scheduler() -> None:
    if not _acquire_scheduler_lock():
        logger.info(
            "Scheduler lock held by another worker process -- skipping startup here."
        )
        return

    # Replaces Legacy's Performance::booted() anti-pattern (ran on every
    # single Model boot); hourly is an arbitrary, reasonable cadence --
    # Legacy itself had no grace period at all, just "runs constantly".
    scheduler.add_job(
        purge_stale_booking_requests,
        "interval",
        hours=1,
        id="purge_stale_booking_requests",
        replace_existing=True,
    )
    # Port of `osa:schedule:send-status-for-upcoming-performances`
    # (BookingLog::checkNotificationForUpcomingPerformances()), Legacy's
    # exact 05:00 daily cadence.
    scheduler.add_job(
        notify_upcoming_booking_status,
        "cron",
        hour=5,
        minute=0,
        id="notify_upcoming_booking_status",
        replace_existing=True,
    )
    # Port of `auth:clear-resets`, Legacy's exact weekly Sunday 02:00 cadence.
    scheduler.add_job(
        purge_expired_password_reset_tokens,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="purge_expired_password_reset_tokens",
        replace_existing=True,
    )
    # Port of `osa:schedule:delete-old-db-log-records`, Legacy's exact
    # daily 23:00 cadence.
    scheduler.add_job(
        purge_old_request_logs,
        "cron",
        hour=23,
        minute=0,
        id="purge_old_request_logs",
        replace_existing=True,
    )

    # Port of Legacy's Schedule::command('osa:schedule:backup-prod-database')
    # ->environments('production') -- the ONLY job in this codebase gated by
    # environment. Two independent conditions (app_environment AND
    # backup_enabled): unlike housekeeping/booking jobs (harmless anywhere),
    # this job writes into a Koofr path SHARED across every stage -- see
    # Settings.backup_enabled's docstring. Uses settings.app_timezone
    # explicitly (Legacy's dailyAt('10:50') meant Vienna wall-clock time) --
    # unlike the four jobs above, which rely on AsyncIOScheduler()'s unset
    # (effectively container-OS/UTC) default timezone; that's a pre-existing
    # gap in this scheduler, out of scope here, but not one this new job
    # should inherit.
    settings = get_settings()
    if settings.app_environment == "production" and settings.backup_enabled:
        scheduler.add_job(
            job_backup_koofr,
            "cron",
            hour=settings.backup_hour,
            minute=settings.backup_minute,
            timezone=ZoneInfo(settings.app_timezone),
            id="backup_koofr",
            replace_existing=True,
        )
    else:
        # Explicit removal (not just "don't add") keeps start_scheduler()
        # idempotent regardless of which environment a previous call ran
        # under -- relevant across repeated calls against this module-level
        # scheduler instance (e.g. across tests), and correct in principle
        # regardless: this branch must always converge to "job absent".
        if scheduler.get_job("backup_koofr") is not None:
            scheduler.remove_job("backup_koofr")
        logger.info(
            "backup_koofr job not registered (app_environment=%s, backup_enabled=%s).",
            settings.app_environment,
            settings.backup_enabled,
        )

    scheduler.add_listener(
        _log_job_outcome, EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
    )
    scheduler.start()
    logger.info("Scheduler started with %d job(s).", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler_lock_conn  # noqa: PLW0603 -- releases the singleton set up in _acquire_scheduler_lock()

    if scheduler.running:
        scheduler.shutdown(wait=False)

    # Undo add_listener() -- start_scheduler() may be called again later
    # (e.g. across tests sharing this module-level scheduler instance),
    # and add_listener() has no replace_existing equivalent.
    scheduler.remove_listener(_log_job_outcome)

    if _scheduler_lock_conn is not None:
        _scheduler_lock_conn.close()
        _scheduler_lock_conn = None

    logger.info("Scheduler stopped.")
