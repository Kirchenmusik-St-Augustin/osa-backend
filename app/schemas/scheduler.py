from pydantic import BaseModel

from app.core.datetime_utils import UtcDatetime


class JobRunOutput(BaseModel):
    """One job_runs row -- the last recorded run of a scheduled job, see
    app.services.job_run_service. `status` stays plain str, not
    Literal["success", "failure"], matching the model layer's own
    Mapped[str] for this native-enum column (see app.db.models.job_run --
    same convention as booking_type_enum on BookingLog): the database's
    ENUM type is what actually enforces the two valid values, so an output
    schema narrowing it further would only fight the ORM's own typing, not
    add any real safety."""

    status: str
    output: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime


class ScheduledJobOutput(BaseModel):
    """One currently-registered scheduled job, as reported live by
    app.services.scheduler_service.get_scheduled_jobs() -- job_id/trigger/
    next_run are computed purely from app.worker.cron_config's catalog,
    `last_run` is the one persisted piece of information, populated from
    the job_runs table (None if the job has never run yet)."""

    id: str
    name: str
    trigger: str
    next_run: str | None
    description: str | None
    last_run: JobRunOutput | None = None


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
