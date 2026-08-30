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


async def purge_stale_booking_requests_task(
    ctx: dict[str, object],  # noqa: ARG001 -- arq's WorkerCoroutine protocol requires a parameter literally named "ctx" (job context, unused by this job)
) -> None:
    await run_in_threadpool(purge_stale_booking_requests)


async def notify_upcoming_booking_status_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(notify_upcoming_booking_status)


async def purge_expired_password_reset_tokens_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(purge_expired_password_reset_tokens)


async def purge_old_request_logs_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(purge_old_request_logs)


async def backup_koofr_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(job_backup_koofr)


async def downsync_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see purge_stale_booking_requests_task
) -> None:
    await run_in_threadpool(job_downsync)
