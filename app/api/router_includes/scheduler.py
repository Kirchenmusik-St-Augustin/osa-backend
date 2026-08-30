from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_guards import require_permission
from app.core.config import get_settings
from app.db.models.user import User
from app.schemas.scheduler import (
    BackupTriggerOutput,
    DownsyncTriggerOutput,
    ScheduledJobOutput,
)
from app.services import scheduler_service
from app.services.backup_service import (
    BackupError,
    list_backups,
    run_backup,
    run_restore,
)

scheduler_router = APIRouter()

_VIEW = Depends(require_permission("schedulerView"))
# Same permission as _VIEW, reused deliberately -- this admin router file
# gates every route (read and action alike) on one permission, matching
# the existing convention elsewhere (e.g. user_administration.py's
# userAdministrate gates both its view and its restore/unlock actions).
_TRIGGER = Depends(require_permission("schedulerView"))

_DOWNSYNC_BLOCKED_IN_PRODUCTION_DETAIL = (
    "Downsync ist in Production nicht verfügbar - Production ist die "
    "führende Datenquelle."
)
_BACKUP_BLOCKED_OUTSIDE_PRODUCTION_DETAIL = (
    "Backup ist außerhalb von Production nicht verfügbar - Production ist "
    "die einzige Stage mit Schreibrechten auf den gemeinsamen "
    "Koofr-Backup-Bestand."
)
_NO_PRODUCTION_BACKUP_DETAIL = "Kein Production-Backup auf Koofr vorhanden."


@scheduler_router.get("/jobs")
def list_scheduled_jobs(
    _current_user: Annotated[User, _VIEW],
) -> list[ScheduledJobOutput]:
    """Pure in-memory computation from the shared cron catalog -- no DB
    session needed, no dependency on the arq worker container actually
    being up right now (see scheduler_service's own docstring)."""
    return scheduler_service.get_scheduled_jobs()


@scheduler_router.post("/backup/trigger", status_code=status.HTTP_201_CREATED)
def trigger_backup(
    _current_user: Annotated[User, _TRIGGER],
) -> BackupTriggerOutput:
    """Manually trigger an immediate Koofr backup, independent of the daily
    scheduled job. Runs synchronously -- FastAPI runs sync `def` handlers in
    a threadpool, so the event loop isn't blocked; no background-job
    infrastructure needed for this DB size. Production-only: the shared
    Koofr path holds one backup history across every stage. Enforced here
    (409, avoiding a misleading 500) AND independently inside run_backup()
    itself, so scripts/backup_db.py and the scheduled job stay protected
    even without going through this endpoint."""
    if get_settings().app_environment != "production":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_BACKUP_BLOCKED_OUTSIDE_PRODUCTION_DETAIL,
        )
    try:
        backup_name = run_backup(manual=True)
    except BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return BackupTriggerOutput(backup_name=backup_name, triggered_at=datetime.now(UTC))


@scheduler_router.post("/downsync/trigger", status_code=status.HTTP_201_CREATED)
def trigger_downsync(
    _current_user: Annotated[User, _TRIGGER],
) -> DownsyncTriggerOutput:
    """Manually trigger an immediate downsync, independent of the nightly
    scheduled job. Runs synchronously -- same reasoning as trigger_backup
    above (single WebDAV download + extract, same cost class, no
    background-job infrastructure needed). Unlike trigger_backup, the
    production gate here is a REAL security boundary, not just UI
    convenience: a production downsync would replace the live database with
    an older snapshot (real data loss since the last backup), so it's
    enforced server-side (409) rather than only hidden in the frontend."""
    if get_settings().app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_DOWNSYNC_BLOCKED_IN_PRODUCTION_DETAIL,
        )

    production_backups = list_backups(stage="production")
    if not production_backups:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NO_PRODUCTION_BACKUP_DETAIL
        )

    try:
        restored_backup = run_restore(backup_name=production_backups[-1])
    except BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return DownsyncTriggerOutput(
        restored_backup=restored_backup, triggered_at=datetime.now(UTC)
    )
