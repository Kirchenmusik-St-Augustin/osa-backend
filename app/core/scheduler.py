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
from collections.abc import Callable
from zoneinfo import ZoneInfo

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobEvent,
    JobExecutionEvent,
)
from apscheduler.job import Job
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

# Central timezone for every job's cron/interval fields below, 1:1 Legacy's
# single config/app.php 'timezone' => 'Europe/Vienna' setting (which
# transparently governed Schedule::command(...)->dailyAt(...) there too).
# A job only needs its own explicit `timezone=` kwarg if it must deviate
# from this default -- none currently do.
scheduler = AsyncIOScheduler(timezone=ZoneInfo(get_settings().app_timezone))

# Shown on the admin-only Scheduler overview (GET /administrator/scheduler/jobs)
# next to each job's id -- keep in sync with every job id start_scheduler()
# can ever register (see test_job_descriptions_covers_every_registrable_job_id).
JOB_DESCRIPTIONS: dict[str, str] = {
    "purge_stale_booking_requests": (
        "Löscht stündlich offene Buchungsanfragen zu bereits vergangenen Terminen."
    ),
    "notify_upcoming_booking_status": (
        "Versendet täglich um 05:00 Uhr eine Buchungsstatus-Mail für "
        "bevorstehende Termine. Nur in Production registriert."
    ),
    "purge_expired_password_reset_tokens": (
        "Löscht wöchentlich (So 02:00 Uhr) abgelaufene Passwort-Reset-"
        "Tokens. Nur in Production registriert."
    ),
    "purge_old_request_logs": (
        "Löscht täglich um 23:00 Uhr Logbuch-Einträge, die älter als 40 "
        "Tage sind. Nur in Production registriert."
    ),
    "backup_koofr": (
        "Sichert die Datenbank täglich nach Koofr. Nur in Production und "
        "wenn BACKUP_ENABLED aktiv ist registriert."
    ),
}

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


def _sync_job_registration(
    job_id: str, *, should_register: bool, add_job: Callable[[], object]
) -> None:
    """Registers a job only when `should_register` is true, otherwise
    ensures it's absent -- shared by every environment-gated job in
    start_scheduler() below so it stays idempotent regardless of which
    environment/settings a previous call ran under (relevant across
    repeated calls against this module-level scheduler instance, e.g.
    across tests)."""
    if should_register:
        add_job()
        return
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)
    logger.info("%s job not registered (should_register=%s).", job_id, should_register)


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

    settings = get_settings()
    is_production = settings.app_environment == "production"

    # Replaces Legacy's Performance::booted() anti-pattern (ran on every
    # single Model boot); hourly is an arbitrary, reasonable cadence --
    # Legacy itself had no grace period at all, just "runs constantly".
    # Deliberately NOT environment-gated: Legacy's booted() hook ran in
    # every environment too -- it was never a Schedule::command(...) entry
    # in routes/console.php in the first place, so that file's
    # `environments('production')` wrapper never applied to it.
    # A cron trigger (fixed :00 of every hour) rather than an interval
    # trigger on purpose: IntervalTrigger anchors its first fire to
    # whatever moment start_scheduler() happened to run, so the actual
    # minute-past-the-hour would silently drift with every container
    # restart -- cron gives a deterministic, restart-independent schedule.
    scheduler.add_job(
        purge_stale_booking_requests,
        "cron",
        minute=0,
        id="purge_stale_booking_requests",
        replace_existing=True,
    )

    # The four jobs below all mirror a real `Schedule::command(...)` entry
    # in Legacy's routes/console.php, and Legacy wraps ALL of them in
    # `if (App::environment('production'))` -- none of them ever ran
    # outside production there. _sync_job_registration() keeps
    # start_scheduler() idempotent regardless of which environment/settings
    # a previous call ran under (relevant across repeated calls against
    # this module-level scheduler instance, e.g. across tests).

    # Port of `osa:schedule:send-status-for-upcoming-performances`
    # (BookingLog::checkNotificationForUpcomingPerformances()), Legacy's
    # exact 05:00 daily cadence.
    _sync_job_registration(
        "notify_upcoming_booking_status",
        should_register=is_production,
        add_job=lambda: scheduler.add_job(
            notify_upcoming_booking_status,
            "cron",
            hour=5,
            minute=0,
            id="notify_upcoming_booking_status",
            replace_existing=True,
        ),
    )
    # Port of `auth:clear-resets`, Legacy's exact weekly Sunday 02:00 cadence.
    _sync_job_registration(
        "purge_expired_password_reset_tokens",
        should_register=is_production,
        add_job=lambda: scheduler.add_job(
            purge_expired_password_reset_tokens,
            "cron",
            day_of_week="sun",
            hour=2,
            minute=0,
            id="purge_expired_password_reset_tokens",
            replace_existing=True,
        ),
    )
    # Port of `osa:schedule:delete-old-db-log-records`, Legacy's exact
    # daily 23:00 cadence.
    _sync_job_registration(
        "purge_old_request_logs",
        should_register=is_production,
        add_job=lambda: scheduler.add_job(
            purge_old_request_logs,
            "cron",
            hour=23,
            minute=0,
            id="purge_old_request_logs",
            replace_existing=True,
        ),
    )
    # Port of Legacy's Schedule::command('osa:schedule:backup-prod-database'),
    # moved from Legacy's exact dailyAt('10:50') to a nighttime slot
    # (Settings.backup_hour/backup_minute, default 03:00) -- deliberate
    # deviation, not a 1:1 cadence port (User decision, 2026-08-13).
    # Two independent conditions (app_environment AND backup_enabled): unlike
    # the three jobs above, this one writes into a Koofr path SHARED across
    # every stage -- see Settings.backup_enabled's docstring. No explicit
    # `timezone=` kwarg needed -- inherits the scheduler-wide default set
    # above.
    _sync_job_registration(
        "backup_koofr",
        should_register=is_production and settings.backup_enabled,
        add_job=lambda: scheduler.add_job(
            job_backup_koofr,
            "cron",
            hour=settings.backup_hour,
            minute=settings.backup_minute,
            id="backup_koofr",
            replace_existing=True,
        ),
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


def _format_next_run(job: Job) -> str | None:
    """Normalizes display to Settings.app_timezone. Trusts
    `job.next_run_time` directly rather than recomputing it from the
    trigger -- unlike the vb-api sister project's multi-worker deployment,
    osa-backend's production Dockerfile runs a single Gunicorn worker
    (--workers 1, see Dockerfile comment), so the process that registers a
    job is always the same one answering this read."""
    if job.next_run_time is None:
        return None
    tz = ZoneInfo(get_settings().app_timezone)
    return job.next_run_time.astimezone(tz).strftime("%d.%m.%Y, %H:%M")


def get_scheduled_jobs() -> list[dict[str, str | None]]:
    """Live introspection of the scheduler's current job registry -- no
    persisted run history, no DB access. Reflects start_scheduler()'s
    environment gating automatically, since it only ever reads whatever is
    actually registered right now."""
    return [
        {
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run": _format_next_run(job),
            "description": JOB_DESCRIPTIONS.get(job.id),
        }
        for job in scheduler.get_jobs()
    ]
