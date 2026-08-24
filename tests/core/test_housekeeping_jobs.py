import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.request_log import RequestLog
from app.services import housekeeping_jobs


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_reset_token(
    db_session: Session, *, email: str, created_at: datetime
) -> PasswordResetToken:
    token = PasswordResetToken(email=email, token="hashed-token", created_at=created_at)
    db_session.add(token)
    db_session.commit()
    return token


def _make_request_log(db_session: Session, *, created_at: datetime) -> RequestLog:
    entry = RequestLog(
        client_ip="127.0.0.1",
        client_ips="[]",
        client_user_agent_id=None,
        user_id=None,
        request_method="GET",
        request_path=_unique("/some/path"),
        request_input="{}",
        response_status=200,
        response_content="null",
        memory_usage=1,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


class TestPurgeExpiredPasswordResetTokens:
    def test_deletes_a_token_older_than_the_ttl(
        self,
        db_session: Session,
    ):
        settings = get_settings()
        expired_at = datetime.now(UTC) - timedelta(
            minutes=settings.password_reset_ttl_minutes + 5
        )
        email = f"{_unique('expired')}@example.test"
        _make_reset_token(db_session, email=email, created_at=expired_at)

        housekeeping_jobs.purge_expired_password_reset_tokens()

        remaining = db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.email == email)
        ).scalar_one_or_none()
        assert remaining is None

    def test_keeps_a_token_still_within_the_ttl(
        self,
        db_session: Session,
    ):
        email = f"{_unique('fresh')}@example.test"
        _make_reset_token(db_session, email=email, created_at=datetime.now(UTC))

        housekeeping_jobs.purge_expired_password_reset_tokens()

        remaining = db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.email == email)
        ).scalar_one_or_none()
        assert remaining is not None


class TestPurgeOldRequestLogs:
    def test_deletes_an_entry_older_than_the_retention_period(
        self,
        db_session: Session,
    ):
        old_entry = _make_request_log(
            db_session, created_at=datetime.now(UTC) - timedelta(days=41)
        )
        # Captured before the job's own SessionLocal() deletes the row --
        # accessing old_entry.id afterwards would try to refresh the
        # (commit-expired) instance and raise ObjectDeletedError.
        old_entry_id = old_entry.id

        housekeeping_jobs.purge_old_request_logs()

        remaining = db_session.execute(
            select(RequestLog).where(RequestLog.id == old_entry_id)
        ).scalar_one_or_none()
        assert remaining is None

    def test_keeps_a_recent_entry(self, db_session: Session):
        recent_entry = _make_request_log(
            db_session, created_at=datetime.now(UTC) - timedelta(days=1)
        )

        housekeeping_jobs.purge_old_request_logs()

        remaining = db_session.execute(
            select(RequestLog).where(RequestLog.id == recent_entry.id)
        ).scalar_one_or_none()
        assert remaining is not None
