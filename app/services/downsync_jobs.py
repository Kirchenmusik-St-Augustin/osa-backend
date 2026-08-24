"""Scheduled downsync job, registered in app.core.scheduler.

Non-production counterpart to backup_jobs.job_backup_koofr: nightly restores
the latest PRODUCTION backup into this stage's own local database, so
dev/test/qa stages regularly get refreshed with real production data.

Like job_backup_koofr, this catches its own errors (only BackupError,
generic exception handling is banned) rather than letting them
propagate to APScheduler's executor -- an unattended, once-daily job must
never itself prevent the scheduler from continuing to fire other jobs.
"""

import logging

from app.core.config import get_settings
from app.services.backup_service import BackupError, list_backups, run_restore

logger = logging.getLogger(__name__)


def job_downsync() -> None:
    # Belt-and-suspenders: app.core.scheduler only ever registers this job
    # outside production, but a future registration bug must never let it
    # actually run against a real production database.
    if get_settings().app_environment == "production":
        logger.error(
            "job_downsync invoked in production -- refusing to run "
            "(registration guard bypassed?)."
        )
        return

    try:
        production_backups = list_backups(stage="production")
    except BackupError:
        logger.exception("Scheduled downsync failed: could not list backups.")
        return

    if not production_backups:
        logger.info("Downsync skipped: no production backup found on Koofr yet.")
        return

    latest = production_backups[-1]
    try:
        run_restore(backup_name=latest)
    except BackupError:
        logger.exception("Scheduled downsync failed.")
        return

    logger.info("Scheduled downsync succeeded: restored %s", latest)
