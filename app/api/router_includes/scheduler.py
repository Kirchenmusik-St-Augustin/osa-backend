from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, require_permission
from app.api.job_queue import JobQueue, get_job_queue
from app.core.config import get_settings
from app.db.database import get_db
from app.schemas.scheduler import JobQueuedOutput, ScheduledJobOutput
from app.services import scheduler_service
from app.worker.scheduled_jobs import manual_backup_task, manual_downsync_task

scheduler_router = APIRouter()

_VIEW = Depends(require_permission("schedulerView"))
# The manual backup and the downsync (which replaces the whole database of a
# stage) have their own permission, so a role that may only look at the
# scheduler can never start them.
_TRIGGER = Depends(require_permission("schedulerTrigger"))

# Ids of the scheduled jobs the triggers stand in for. They double as the
# queue's job ids, so a trigger is dropped while the nightly run (or an
# earlier trigger) of the same job is queued or running.
_BACKUP_JOB_ID = "backup_koofr"
_DOWNSYNC_JOB_ID = "downsync"

_DOWNSYNC_BLOCKED_IN_PRODUCTION_DETAIL = (
    "Downsync ist in Production nicht verfügbar - Production ist die "
    "führende Datenquelle."
)
_BACKUP_BLOCKED_OUTSIDE_PRODUCTION_DETAIL = (
    "Backup ist außerhalb von Production nicht verfügbar - Production ist "
    "die einzige Stage mit Schreibrechten auf den gemeinsamen "
    "Koofr-Backup-Bestand."
)


@scheduler_router.get("/jobs")
def list_scheduled_jobs(
    _current_user: Annotated[AuthUser, _VIEW],
    db: Annotated[Session, Depends(get_db)],
) -> list[ScheduledJobOutput]:
    """Trigger/next_run are pure in-memory computation from the shared cron
    catalog -- no dependency on the arq worker container actually being up
    right now (see scheduler_service's own docstring). `last_run` is the
    one field that does need a DB session, read from the persisted
    job_runs table."""
    return scheduler_service.get_scheduled_jobs(db)


@scheduler_router.post("/backup/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_backup(
    _current_user: Annotated[AuthUser, _TRIGGER],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobQueuedOutput:
    """Hands an immediate Koofr backup, independent of the daily scheduled
    job, to the worker container. The web process never runs backups
    itself, so it needs neither the Koofr credentials nor the PostgreSQL
    client tools, and a long dump cannot hit the request timeout; the
    outcome is the `last_run` of the `backup_koofr` job. Production-only:
    the shared Koofr path holds one backup history across every stage.
    Enforced here (409, avoiding a misleading failed run) AND independently
    inside run_backup() itself, so scripts/backup_db.py and the scheduled
    job stay protected even without going through this endpoint."""
    if get_settings().app_environment != "production":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_BACKUP_BLOCKED_OUTSIDE_PRODUCTION_DETAIL,
        )
    job_queue.enqueue_once(manual_backup_task, _BACKUP_JOB_ID)
    return JobQueuedOutput(job_id=_BACKUP_JOB_ID, queued_at=datetime.now(UTC))


@scheduler_router.post("/downsync/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_downsync(
    _current_user: Annotated[AuthUser, _TRIGGER],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JobQueuedOutput:
    """Hands an immediate downsync, independent of the nightly scheduled
    job, to the worker container; the outcome is the `last_run` of the
    `downsync` job. Unlike trigger_backup, the production gate here is a
    REAL security boundary, not just UI convenience: a production downsync
    would replace the live database with an older snapshot (real data loss
    since the last backup), so it's enforced server-side (409) rather than
    only hidden in the frontend."""
    if get_settings().app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_DOWNSYNC_BLOCKED_IN_PRODUCTION_DETAIL,
        )
    job_queue.enqueue_once(manual_downsync_task, _DOWNSYNC_JOB_ID)
    return JobQueuedOutput(job_id=_DOWNSYNC_JOB_ID, queued_at=datetime.now(UTC))
