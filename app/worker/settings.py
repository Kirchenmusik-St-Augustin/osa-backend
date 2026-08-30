"""arq WorkerSettings for the dedicated osa-backend-worker container (see
osa-deploy's osa-backend-worker Quadlet) -- entry point:
`arq app.worker.settings.WorkerSettings`. Runs every cron job AND every
on-demand (former BackgroundTasks) job; the web container never runs
either of these itself anymore.
"""

import logging
from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from arq.typing import WorkerCoroutine

from app.core.arq_pool import build_redis_settings
from app.core.config import get_settings
from app.core.datetime_utils import get_app_timezone
from app.core.logging_config import setup_logging
from app.db import (
    base as _,  # noqa: F401 -- populates SQLAlchemy's mapper registry (string-based relationship() resolution); required here because this worker process never imports main.py, which is where the web process normally does this same import
)
from app.worker.cron_config import CronSchedule, build_cron_catalog
from app.worker.scheduled_jobs import (
    backup_koofr_task,
    downsync_task,
    notify_upcoming_booking_status_task,
    purge_expired_password_reset_tokens_task,
    purge_old_request_logs_task,
    purge_stale_booking_requests_task,
)
from app.worker.tasks import (
    send_booked_or_standby_canceled_email_task,
    send_new_registration_notice_task,
    send_password_reset_email_task,
    send_user_message_email_task,
    send_verification_email_task,
)

logger = logging.getLogger(__name__)

_JOB_COROUTINES: dict[str, WorkerCoroutine] = {
    "purge_stale_booking_requests": purge_stale_booking_requests_task,
    "notify_upcoming_booking_status": notify_upcoming_booking_status_task,
    "purge_expired_password_reset_tokens": purge_expired_password_reset_tokens_task,
    "purge_old_request_logs": purge_old_request_logs_task,
    "backup_koofr": backup_koofr_task,
    "downsync": downsync_task,
}


def _build_cron_job(schedule: CronSchedule) -> CronJob:
    return cron(
        _JOB_COROUTINES[schedule.job_id],
        month=schedule.month,
        day=schedule.day,
        weekday=schedule.weekday,
        hour=schedule.hour,
        minute=schedule.minute,
        second=schedule.second,
        microsecond=schedule.microsecond,
        job_id=schedule.job_id,
    )


async def _on_startup(_ctx: dict[str, object]) -> None:
    logger.info("osa-backend arq worker started.")


async def _on_shutdown(_ctx: dict[str, object]) -> None:
    logger.info("osa-backend arq worker shutting down.")


setup_logging()

_settings = get_settings()
_active_schedules = [
    schedule for schedule in build_cron_catalog(_settings) if schedule.active
]


class WorkerSettings:
    """Never instantiated -- arq's CLI reads these as plain class
    attributes (see arq.typing.WorkerSettingsBase), so ClassVar is the
    semantically correct annotation, not just a lint workaround."""

    functions: ClassVar[list[WorkerCoroutine]] = [
        send_new_registration_notice_task,
        send_verification_email_task,
        send_password_reset_email_task,
        send_booked_or_standby_canceled_email_task,
        send_user_message_email_task,
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        _build_cron_job(schedule) for schedule in _active_schedules
    ]
    redis_settings: RedisSettings = build_redis_settings()
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    timezone = get_app_timezone()
