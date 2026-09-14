"""Scheduled Koofr backup job, registered in
app.worker.settings.WorkerSettings (see app.worker.cron_config for the
shared timing catalog).

Unlike housekeeping_jobs.py/booking_jobs.py (which deliberately let
exceptions propagate to arq's own Worker.run_job(), which already
logs/isolates a job's exception), this job catches its own errors: an
unattended, once-daily external-network job whose sole purpose is
safety-netting the production database must never itself prevent the
worker from continuing to fire other jobs, and backup_service.BackupError
already carries a far more actionable message than arq's generic job-error
log line. Only BackupError is caught -- generic exception handling is
still banned; this narrows to the one exception type backup_service ever
raises.

Records its own outcome via app.services.job_run_service.record_job_run()
rather than going through app.worker.scheduled_jobs._run_and_record()'s
generic wrapper: this function has multiple meaningful exit points with
partial-success nuance a generic success/failure wrapper cannot reproduce
(a failed retention cleanup after a successful backup still counts as an
overall success, see below).
"""

import logging
from datetime import UTC, datetime

from app.services.backup_service import BackupError, cleanup_old_backups, run_backup
from app.services.job_run_service import record_job_run

logger = logging.getLogger(__name__)

_JOB_ID = "backup_koofr"


def job_backup_koofr() -> None:
    started_at = datetime.now(UTC)

    try:
        backup_name = run_backup()
    except BackupError as exc:
        logger.exception("Scheduled Koofr backup failed.")
        record_job_run(_JOB_ID, started_at, status="failure", output=str(exc))
        return

    logger.info("Scheduled Koofr backup succeeded: %s", backup_name)

    try:
        deleted = cleanup_old_backups()
    except BackupError as exc:
        logger.exception(
            "Koofr backup retention cleanup failed (backup %s still succeeded).",
            backup_name,
        )
        # Overall success, not failure: the backup itself -- this job's
        # actual safety-net purpose -- succeeded, only the older-backup
        # housekeeping afterward failed. output explains the caveat so an
        # admin reading the last-run status isn't misled into thinking
        # nothing went wrong.
        record_job_run(
            _JOB_ID,
            started_at,
            status="success",
            output=(
                f"Backup {backup_name} succeeded, but retention cleanup failed: {exc}"
            ),
        )
        return

    output = f"Cleaned up {len(deleted)} expired backup(s)." if deleted else None
    if deleted:
        logger.info("Cleaned up %d expired Koofr backup(s).", len(deleted))
    record_job_run(_JOB_ID, started_at, status="success", output=output)
