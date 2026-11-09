"""Scheduled hygiene jobs, registered in app.worker.settings.WorkerSettings
(see app.worker.cron_config for the shared timing catalog).

Same pattern as booking_jobs.py: each function opens its own short-lived
SessionLocal() (documented exception to the SessionLocal-outside-Depends
ruff ban, see pyproject.toml's per-file-ignores), and exceptions are
deliberately NOT caught here -- arq's own Worker.run_job() already logs a
job's exception and keeps the worker running. Their outcome is recorded by
app.worker.scheduled_jobs._run_and_record(), the async wrapper that
actually invokes these functions.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, or_

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.db.models.auth_log import AuthLog
from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.request_log import RequestLog
from app.db.models.sent_email import SentEmail

# Fixed retention for the two log tables that hold personal data
# (deliberately not config values).
_REQUEST_LOG_RETENTION_DAYS = 40
_AUTH_LOG_RETENTION_DAYS = 365
_SENT_EMAIL_RETENTION_DAYS = 365


def purge_expired_password_reset_tokens() -> None:
    """Sweeps password_reset_tokens rows that were requested but never used/completed
    and simply expired. auth_service.request_password_reset()/
    execute_password_reset() already delete a row opportunistically on the
    next request/successful reset, but nothing previously flushed a row
    that was just abandoned."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.password_reset_ttl_minutes)
    db = SessionLocal()
    try:
        # synchronize_session=False: a bulk DELETE never needs to keep loaded
        # ORM objects in sync (the session is closed right below).
        db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.created_at <= cutoff),
            execution_options={"synchronize_session": False},
        )
        db.commit()
    finally:
        db.close()


def purge_old_request_logs() -> None:
    """Retention sweep of what grows with use: request_logs older than 40 days
    (see _REQUEST_LOG_RETENTION_DAYS) and the user-agent strings no request log
    refers to any more, auth_logs older than a year (see
    _AUTH_LOG_RETENTION_DAYS; the login throttle only reads the last 15
    minutes), sent_emails older than a year (see _SENT_EMAIL_RETENTION_DAYS;
    the stored bodies hold one-time links and personal data) and sessions that
    can no longer be used, past the absolute lifetime or idle for longer than
    the idle timeout (a dead session's row would otherwise stay until its
    owner happens to present the dead token).
    Registered under the one existing job id."""
    settings = get_settings()
    now = datetime.now(UTC)
    request_log_cutoff = now - timedelta(days=_REQUEST_LOG_RETENTION_DAYS)
    auth_log_cutoff = now - timedelta(days=_AUTH_LOG_RETENTION_DAYS)
    sent_email_cutoff = now - timedelta(days=_SENT_EMAIL_RETENTION_DAYS)
    session_lifetime_cutoff = now - timedelta(days=settings.refresh_token_lifetime_days)
    session_idle_cutoff = now - timedelta(minutes=settings.session_idle_timeout_minutes)
    db = SessionLocal()
    try:
        # synchronize_session=False: bulk DELETEs never need to keep loaded ORM
        # objects in sync (the session is closed right below).
        db.execute(
            delete(RequestLog).where(RequestLog.created_at <= request_log_cutoff),
            execution_options={"synchronize_session": False},
        )
        # User-agent strings no remaining request log points at.
        db.execute(
            delete(ClientUserAgent).where(
                ~exists().where(RequestLog.client_user_agent_id == ClientUserAgent.id)
            ),
            execution_options={"synchronize_session": False},
        )
        db.execute(
            delete(AuthLog).where(AuthLog.fired_at <= auth_log_cutoff),
            execution_options={"synchronize_session": False},
        )
        db.execute(
            delete(SentEmail).where(SentEmail.created_at <= sent_email_cutoff),
            execution_options={"synchronize_session": False},
        )
        db.execute(
            delete(PersonalAccessToken).where(
                or_(
                    PersonalAccessToken.created_at <= session_lifetime_cutoff,
                    func.coalesce(
                        PersonalAccessToken.last_used_at, PersonalAccessToken.created_at
                    )
                    <= session_idle_cutoff,
                )
            ),
            execution_options={"synchronize_session": False},
        )
        db.commit()
    finally:
        db.close()
