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


async def _run_and_record(job_id: str, func: Callable[[], None]) -> None:
    """Shared wrapper for the four simple, single-exit-point job bodies
    below (they already let exceptions propagate, no internal try/except --
    see their own docstrings) -- observes success/failure correctly without
    each of them needing its own record_job_run() call.

    backup_koofr_task/downsync_task deliberately do NOT use this: those two
    job bodies have their own multiple, meaningful exit points (see
    app.services.backup_jobs/downsync_jobs) that a single generic
    success/failure wrapper cannot reproduce, so they record their own
    outcome instead. Re-raising after recording keeps arq's own existing
    job-lifecycle log line (and the scheduled/triggered log-filter tagging)
    unchanged -- purely additive, no regression in current log behavior.
    """
    started_at = datetime.now(UTC)
    try:
        await run_in_threadpool(func)
    except Exception:
        record_job_run(
            job_id, started_at, status="failure", output=traceback.format_exc()
        )
        raise
    else:
        record_job_run(job_id, started_at, status="success", output=None)


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
    await run_in_threadpool(job_backup_koofr)


async def downsync_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(job_downsync)
