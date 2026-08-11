"""Scheduled Koofr backup job, registered in app.core.scheduler.

Unlike housekeeping_jobs.py/booking_jobs.py (which deliberately let
exceptions propagate to APScheduler's own executor), this job catches its
own errors: an unattended, once-daily external-network job whose sole
purpose is safety-netting the production database must never itself
prevent the scheduler from continuing to fire other jobs, and
backup_service.BackupError already carries a far more actionable message
than APScheduler's generic "job errored" log line. Only BackupError is
caught -- CLAUDE.md still bans generic exception handling; this narrows to
the one exception type backup_service ever raises.
"""

import logging

from app.services.backup_service import BackupError, cleanup_old_backups, run_backup

logger = logging.getLogger(__name__)


def job_backup_koofr() -> None:
    try:
        backup_name = run_backup()
    except BackupError:
        logger.exception("Scheduled Koofr backup failed.")
        return

    logger.info("Scheduled Koofr backup succeeded: %s", backup_name)

    try:
        deleted = cleanup_old_backups()
    except BackupError:
        logger.exception(
            "Koofr backup retention cleanup failed (backup %s still succeeded).",
            backup_name,
        )
        return

    if deleted:
        logger.info("Cleaned up %d expired Koofr backup(s).", len(deleted))
