from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_guards import require_permission
from app.core.scheduler import get_scheduled_jobs
from app.db.models.user import User
from app.schemas.scheduler import BackupTriggerOutput, ScheduledJobOutput
from app.services.backup_service import BackupError, run_backup

scheduler_router = APIRouter()

_VIEW = Depends(require_permission("schedulerView"))
# Same permission as _VIEW, reused deliberately -- this admin router file
# gates every route (read and action alike) on one permission, matching
# the existing convention elsewhere (e.g. user_administration.py's
# userAdministrate gates both its view and its restore/unlock actions).
_TRIGGER = Depends(require_permission("schedulerView"))


@scheduler_router.get("/jobs")
def list_scheduled_jobs(
    _current_user: Annotated[User, _VIEW],
) -> list[ScheduledJobOutput]:
    """Pure in-memory introspection of the running scheduler -- no DB
    session needed."""
    return [ScheduledJobOutput.model_validate(job) for job in get_scheduled_jobs()]


@scheduler_router.post("/backup/trigger", status_code=status.HTTP_201_CREATED)
def trigger_backup(
    _current_user: Annotated[User, _TRIGGER],
) -> BackupTriggerOutput:
    """Manually trigger an immediate Koofr backup, independent of the daily
    scheduled job. Runs synchronously -- FastAPI runs sync `def` handlers in
    a threadpool, so the event loop isn't blocked; no background-job
    infrastructure needed for this DB size (same reasoning as vb-api's
    equivalent endpoint). Deliberately callable in every stage server-side
    (the shared Koofr path makes a stage gate here pure UI convenience, not
    a real security boundary) -- only the frontend restricts this to
    production; the permission check above still applies in every stage."""
    try:
        backup_name = run_backup(manual=True)
    except BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return BackupTriggerOutput(backup_name=backup_name, triggered_at=datetime.now(UTC))
