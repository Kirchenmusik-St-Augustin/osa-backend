from pydantic import BaseModel

from app.core.datetime_utils import UtcDatetime


class ScheduledJobOutput(BaseModel):
    """One currently-registered APScheduler job, as reported live by
    app.core.scheduler.get_scheduled_jobs() -- no persisted run history."""

    id: str
    name: str
    trigger: str
    next_run: str | None
    description: str | None


class BackupTriggerOutput(BaseModel):
    """Response of a manually triggered Koofr backup
    (POST /administrator/scheduler/backup/trigger)."""

    backup_name: str
    triggered_at: UtcDatetime


class DownsyncTriggerOutput(BaseModel):
    """Response of a manually triggered downsync
    (POST /administrator/scheduler/downsync/trigger)."""

    restored_backup: str
    triggered_at: UtcDatetime
