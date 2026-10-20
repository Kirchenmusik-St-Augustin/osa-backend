"""Thin async wrappers around the existing (unchanged) synchronous cron
job bodies, registered as arq CronJobs in app.worker.settings.WorkerSettings.
Each job body itself stays exactly as it already was (own SessionLocal(),
own exception handling) -- only this wrapper is new, and it exists purely
to (a) satisfy arq's requirement that a cron_jobs= entry be a coroutine
function, and (b) run the actual (blocking, synchronous DB) job body via a
thread instead of directly on the worker's event loop, so one slow job
(e.g. downsync's WebDAV download) never blocks arq from picking up any
other concurrently-due job in the same worker process.
"""

import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.services.backup_jobs import job_backup_koofr
from app.services.booking_jobs import (
    notify_upcoming_booking_status,
    purge_stale_booking_requests,
)
from app.services.downsync_jobs import job_downsync
from app.services.housekeeping_jobs import (
    purge_expired_password_reset_tokens,
    purge_old_request_logs,
)
from app.services.job_run_service import record_job_run

if TYPE_CHECKING:
    from collections.abc import Callable


def _failure_output(exc: Exception) -> str:
    """Exception type and message, not the traceback. A database error keeps
    only the first line of the driver message: SQLAlchemy appends the
    statement with its bound parameters, and the driver echoes the offending
    part of the statement and the key values, all of it personal data in a
    text that administrators read and that is copied into every backup."""
    if isinstance(exc, SQLAlchemyError):
        driver_error = getattr(exc, "orig", None) or exc
        lines = str(driver_error).strip().splitlines()
        return f"{type(exc).__name__}: {lines[0] if lines else ''}".rstrip()
    return "".join(traceback.format_exception_only(exc)).strip()


async def _run_and_record(job_id: str, func: Callable[[], None]) -> None:
    """Shared wrapper for the four simple, single-exit-point job bodies
    below (they already let exceptions propagate, no internal try/except --
    see their own docstrings) -- observes success/failure correctly without
    each of them needing its own record_job_run() call.

    backup_koofr_task/downsync_task use _run_self_recording() instead: those
    two job bodies have their own multiple, meaningful exit points (see
    app.services.backup_jobs/downsync_jobs) that a single generic
    success/failure wrapper cannot reproduce, so they record their own
    outcome. Re-raising after recording keeps arq's own existing
    job-lifecycle log line (and the scheduled/triggered log-filter tagging)
    unchanged -- purely additive, no regression in current log behavior.
    """
    started_at = datetime.now(UTC)
    try:
        await run_in_threadpool(func)
    except Exception as exc:
        await run_in_threadpool(
            record_job_run,
            job_id,
            started_at,
            status="failure",
            output=_failure_output(exc),
        )
        raise
    else:
        await run_in_threadpool(
            record_job_run, job_id, started_at, status="success", output=None
        )


async def _run_self_recording(job_id: str, func: Callable[[], None]) -> None:
    """For job bodies that record their own outcome: only an exception that
    escapes the body (anything but the BackupError it handles itself, for
    example an OSError from a temporary file) is recorded here, so the
    scheduler view cannot keep showing the last success while the job is
    failing."""
    started_at = datetime.now(UTC)
    try:
        await run_in_threadpool(func)
    except Exception as exc:
        await run_in_threadpool(
            record_job_run,
            job_id,
            started_at,
            status="failure",
            output=_failure_output(exc),
        )
        raise


async def purge_stale_booking_requests_task(
    ctx: dict[str, object],  # noqa: ARG001 -- arq's WorkerCoroutine protocol requires a parameter literally named "ctx" (job context, unused by this job)
) -> None:
    await _run_and_record("purge_stale_booking_requests", purge_stale_booking_requests)


async def notify_upcoming_booking_status_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await _run_and_record(
        "notify_upcoming_booking_status", notify_upcoming_booking_status
    )


async def purge_expired_password_reset_tokens_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await _run_and_record(
        "purge_expired_password_reset_tokens", purge_expired_password_reset_tokens
    )


async def purge_old_request_logs_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await _run_and_record("purge_old_request_logs", purge_old_request_logs)


async def backup_koofr_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await _run_self_recording("backup_koofr", job_backup_koofr)


async def downsync_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await _run_self_recording("downsync", job_downsync)
