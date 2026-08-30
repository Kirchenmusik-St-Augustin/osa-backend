"""Admin Scheduler overview (GET /administrator/scheduler/jobs) -- computes
a purely theoretical next-run listing directly from app.worker.cron_config's
shared catalog. Unlike the previous APScheduler-based version of this
function, this does NOT read the actual arq worker process's live state --
it can't: arq's cron scheduling is computed in-memory inside whichever
process is actually running the worker, and nothing publishes that
externally. Since the worker builds its own cron_jobs= from this exact
same catalog (see app.worker.settings.WorkerSettings), the two displays
can never disagree in content -- but this endpoint's response no longer
confirms that the worker container is actually up and running right now,
only that it *would* run these jobs on this schedule if it is.
"""

from datetime import datetime

from arq.cron import next_cron

from app.core.config import Settings, get_settings
from app.core.datetime_utils import get_app_timezone
from app.schemas.scheduler import ScheduledJobOutput
from app.worker.cron_config import CronSchedule, build_cron_catalog

_TRIGGER_FIELDS = ("month", "day", "weekday", "hour", "minute", "second")


def _trigger_display(schedule: CronSchedule) -> str:
    parts = [
        f"{name}='{getattr(schedule, name)}'"
        for name in _TRIGGER_FIELDS
        if getattr(schedule, name) is not None
    ]
    return f"cron[{', '.join(parts)}]"


def _next_run_display(schedule: CronSchedule) -> str:
    now = datetime.now(get_app_timezone())
    next_run = next_cron(
        now,
        month=schedule.month,
        day=schedule.day,
        weekday=schedule.weekday,
        hour=schedule.hour,
        minute=schedule.minute,
        second=schedule.second,
        microsecond=schedule.microsecond,
    )
    return next_run.astimezone(get_app_timezone()).strftime("%d.%m.%Y, %H:%M")


def _to_output(schedule: CronSchedule) -> ScheduledJobOutput:
    return ScheduledJobOutput(
        id=schedule.job_id,
        name=schedule.job_id,
        trigger=_trigger_display(schedule),
        next_run=_next_run_display(schedule),
        description=schedule.description,
    )


def get_scheduled_jobs(settings: Settings | None = None) -> list[ScheduledJobOutput]:
    active_settings = settings or get_settings()
    return [
        _to_output(schedule)
        for schedule in build_cron_catalog(active_settings)
        if schedule.active
    ]
