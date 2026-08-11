"""Scheduled hygiene jobs, registered in app.core.scheduler.

Same pattern as booking_jobs.py: each function opens its own short-lived
SessionLocal() (documented exception to the SessionLocal-outside-Depends
ruff ban, see pyproject.toml's per-file-ignores), and exceptions are
deliberately NOT caught here -- APScheduler's own executor already logs a
job's exception and keeps the scheduler running.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.request_log import RequestLog

# 1:1 Legacy's OsaScheduleDeleteOldDbLogRecords hardcoded literal (never a
# config value there either).
_REQUEST_LOG_RETENTION_DAYS = 40


def purge_expired_password_reset_tokens() -> None:
    """Port of Laravel's stock `auth:clear-resets` command -- sweeps
    password_reset_tokens rows that were requested but never used/completed
    and simply expired. auth_service.request_password_reset()/
    execute_password_reset() already delete a row opportunistically on the
    next request/successful reset, but nothing previously flushed a row
    that was just abandoned."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.password_reset_ttl_minutes)
    db = SessionLocal()
    try:
        db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.created_at <= cutoff)
        )
        db.commit()
    finally:
        db.close()


def purge_old_request_logs() -> None:
    """Port of `osa:schedule:delete-old-db-log-records` --
    `RequestLog::where('created_at', '<=', now()->subDays(40))->delete()`."""
    cutoff = datetime.now(UTC) - timedelta(days=_REQUEST_LOG_RETENTION_DAYS)
    db = SessionLocal()
    try:
        db.execute(delete(RequestLog).where(RequestLog.created_at <= cutoff))
        db.commit()
    finally:
        db.close()
