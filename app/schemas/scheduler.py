from pydantic import BaseModel


class ScheduledJobOutput(BaseModel):
    """One currently-registered APScheduler job, as reported live by
    app.core.scheduler.get_scheduled_jobs() -- no persisted run history."""

    id: str
    name: str
    trigger: str
    next_run: str | None
    description: str | None
