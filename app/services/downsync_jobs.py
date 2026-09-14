"""Scheduled downsync job, registered in app.worker.settings.WorkerSettings
(see app.worker.cron_config for the shared timing catalog).

Non-production counterpart to backup_jobs.job_backup_koofr: nightly restores
the latest PRODUCTION backup into this stage's own local database, so
dev/test/qa stages regularly get refreshed with real production data.

Like job_backup_koofr, this catches its own errors (only BackupError,
generic exception handling is banned) rather than letting them propagate to
arq's own Worker.run_job() -- an unattended, once-daily job must never
itself prevent the worker from continuing to fire other jobs.

Records its own outcome via app.services.job_run_service.record_job_run()
rather than going through app.worker.scheduled_jobs._run_and_record()'s
generic wrapper: this function has five distinct exit points (see below),
more nuance than a generic success/failure wrapper can reproduce.
"""

import logging
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.backup_service import BackupError, list_backups, run_restore
from app.services.job_run_service import record_job_run

logger = logging.getLogger(__name__)

_JOB_ID = "downsync"


def job_downsync() -> None:
    started_at = datetime.now(UTC)

    # Belt-and-suspenders: app.worker.cron_config only ever registers this
    # job outside production, but a future registration bug must never let
    # it actually run against a real production database.
    if get_settings().app_environment == "production":
        message = (
            "job_downsync invoked in production -- refusing to run "
            "(registration guard bypassed?)."
        )
        logger.error(message)
        record_job_run(_JOB_ID, started_at, status="failure", output=message)
        return

    try:
        production_backups = list_backups(stage="production")
    except BackupError as exc:
        logger.exception("Scheduled downsync failed: could not list backups.")
        record_job_run(
            _JOB_ID,
            started_at,
            status="failure",
            output=f"Could not list backups: {exc}",
        )
        return

    if not production_backups:
        message = "Downsync skipped: no production backup found on Koofr yet."
        logger.info(message)
        # Success, not failure: the job correctly found nothing to do yet
        # (e.g. production's very first backup hasn't run yet) -- there was
        # no error, just nothing to sync.
        record_job_run(_JOB_ID, started_at, status="success", output=message)
        return

    latest = production_backups[-1]
    try:
        run_restore(backup_name=latest)
    except BackupError as exc:
        logger.exception("Scheduled downsync failed.")
        record_job_run(_JOB_ID, started_at, status="failure", output=str(exc))
        return

    logger.info("Scheduled downsync succeeded: restored %s", latest)
    record_job_run(_JOB_ID, started_at, status="success", output=f"Restored {latest}.")
