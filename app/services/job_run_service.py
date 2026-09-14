"""Persisted "last run" tracking for the six scheduled cron jobs (see
app.worker.cron_config) -- one job_runs row per completed run, read back by
app.services.scheduler_service.get_scheduled_jobs() for the admin Scheduler
overview.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models.job_run import JobRun

logger = logging.getLogger(__name__)


def record_job_run(
    job_id: str,
    started_at: datetime,
    *,
    status: Literal["success", "failure"],
    output: str | None,
) -> None:
    """Writes one job_runs row. Opens its own SessionLocal() -- called from
    worker code with no request context, the documented exception to the
    SessionLocal-outside-Depends ban (see pyproject.toml's
    per-file-ignores, same pattern as app.services.booking_jobs).

    Catches Exception broadly and only logs -- the one deliberate, narrowly
    scoped exception to this project's ban on generic except Exception
    handling: this function's entire purpose is best-effort observability,
    and a failure to write an audit row (a DB hiccup, a constraint edge
    case) must never be the reason a real scheduled job's own
    success/failure handling breaks.
    """
    try:
        db = SessionLocal()
        try:
            db.add(
                JobRun(
                    job_id=job_id,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=status,
                    output=output,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to record job run for %s", job_id)


def get_latest_run_per_job(db: Session) -> dict[str, JobRun]:
    """One query, not one-per-job -- SELECT DISTINCT ON (job_id) ... ORDER
    BY job_id, started_at DESC, Postgres's own idiom for "latest row per
    group". Required for the N+1 guard in the Scheduler overview."""
    stmt = (
        select(JobRun)
        .distinct(JobRun.job_id)
        .order_by(JobRun.job_id, JobRun.started_at.desc())
    )
    return {run.job_id: run for run in db.execute(stmt).scalars().all()}
