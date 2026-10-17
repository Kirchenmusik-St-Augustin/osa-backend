import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.auth_log import AuthLog
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.request_log import RequestLog
from app.services import housekeeping_jobs

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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
        client_ips=[],
        client_user_agent_id=None,
        user_id=None,
        request_method="GET",
        request_path=_unique("/some/path"),
        request_input={},
        response_status=200,
        response_content=None,
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


def _make_auth_log(db_session: Session, *, age_days: int) -> AuthLog:
    entry = AuthLog(
        event="Login",
        fired_at=datetime.now(UTC) - timedelta(days=age_days),
        email=f"{_unique('purge')}@example.test",
        payload={},
    )
    db_session.add(entry)
    db_session.commit()
    return entry


class TestPurgeOldAuthLogs:
    def test_deletes_an_entry_older_than_a_year_and_keeps_a_recent_one(
        self, db_session: Session
    ):
        old_entry = _make_auth_log(db_session, age_days=400)
        recent_entry = _make_auth_log(db_session, age_days=30)
        # Captured before the job's own session deletes the old row.
        old_id, recent_id = old_entry.id, recent_entry.id

        housekeeping_jobs.purge_old_request_logs()

        remaining = set(
            db_session.execute(
                select(AuthLog.id).where(AuthLog.id.in_([old_id, recent_id]))
            ).scalars()
        )
        assert remaining == {recent_id}

    def test_keeps_an_entry_just_inside_the_retention_period(self, db_session: Session):
        inside_entry = _make_auth_log(db_session, age_days=364)

        housekeeping_jobs.purge_old_request_logs()

        remaining = db_session.execute(
            select(AuthLog.id).where(AuthLog.id == inside_entry.id)
        ).scalar_one_or_none()
        assert remaining is not None

    def test_deletes_an_entry_just_outside_the_retention_period(
        self, db_session: Session
    ):
        outside_entry = _make_auth_log(db_session, age_days=366)
        outside_id = outside_entry.id

        housekeeping_jobs.purge_old_request_logs()

        remaining = db_session.execute(
            select(AuthLog.id).where(AuthLog.id == outside_id)
        ).scalar_one_or_none()
        assert remaining is None

    def test_the_request_log_retention_is_unaffected(self, db_session: Session):
        thirty_day_old_request_log = _make_request_log(
            db_session, created_at=datetime.now(UTC) - timedelta(days=30)
        )
        old_request_log = _make_request_log(
            db_session, created_at=datetime.now(UTC) - timedelta(days=41)
        )
        old_request_log_id = old_request_log.id

        housekeeping_jobs.purge_old_request_logs()

        kept = db_session.execute(
            select(RequestLog.id).where(RequestLog.id == thirty_day_old_request_log.id)
        ).scalar_one_or_none()
        gone = db_session.execute(
            select(RequestLog.id).where(RequestLog.id == old_request_log_id)
        ).scalar_one_or_none()
        assert kept is not None
        assert gone is None


def _make_session(
    db_session: Session,
    user_id: uuid.UUID,
    *,
    created_ago: timedelta,
    last_used_ago: timedelta | None,
) -> uuid.UUID:
    now = datetime.now(UTC)
    session = PersonalAccessToken(
        user_id=user_id,
        name="session",
        token=_unique("jti"),
        created_at=now - created_ago,
        last_used_at=None if last_used_ago is None else now - last_used_ago,
    )
    db_session.add(session)
    db_session.commit()
    return session.id


def _surviving(db_session: Session, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    return set(
        db_session.execute(
            select(PersonalAccessToken.id).where(PersonalAccessToken.id.in_(ids))
        ).scalars()
    )


class TestPurgeDeadSessions:
    def test_deletes_a_session_past_the_absolute_lifetime(
        self, db_session: Session, make_user
    ):
        user = make_user()
        lifetime = timedelta(days=get_settings().refresh_token_lifetime_days)
        old = _make_session(
            db_session,
            user.id,
            created_ago=lifetime + timedelta(hours=1),
            last_used_ago=timedelta(minutes=1),
        )

        housekeeping_jobs.purge_old_request_logs()

        assert _surviving(db_session, [old]) == set()

    def test_deletes_a_session_idle_for_longer_than_the_timeout(
        self, db_session: Session, make_user
    ):
        user = make_user()
        idle = timedelta(minutes=get_settings().session_idle_timeout_minutes)
        stale = _make_session(
            db_session,
            user.id,
            created_ago=timedelta(hours=5),
            last_used_ago=idle + timedelta(minutes=1),
        )

        housekeeping_jobs.purge_old_request_logs()

        assert _surviving(db_session, [stale]) == set()

    def test_keeps_a_live_session_and_one_just_inside_both_limits(
        self, db_session: Session, make_user
    ):
        user = make_user()
        settings = get_settings()
        live = _make_session(
            db_session,
            user.id,
            created_ago=timedelta(days=1),
            last_used_ago=timedelta(minutes=5),
        )
        at_the_edge = _make_session(
            db_session,
            user.id,
            created_ago=timedelta(days=settings.refresh_token_lifetime_days)
            - timedelta(hours=1),
            last_used_ago=timedelta(minutes=settings.session_idle_timeout_minutes)
            - timedelta(minutes=1),
        )

        housekeeping_jobs.purge_old_request_logs()

        assert _surviving(db_session, [live, at_the_edge]) == {live, at_the_edge}

    def test_a_session_never_used_counts_from_its_creation(
        self, db_session: Session, make_user
    ):
        user = make_user()
        idle = timedelta(minutes=get_settings().session_idle_timeout_minutes)
        fresh = _make_session(
            db_session, user.id, created_ago=timedelta(minutes=5), last_used_ago=None
        )
        stale = _make_session(
            db_session,
            user.id,
            created_ago=idle + timedelta(minutes=1),
            last_used_ago=None,
        )

        housekeeping_jobs.purge_old_request_logs()

        assert _surviving(db_session, [fresh, stale]) == {fresh}

    def test_only_dead_sessions_of_a_user_with_a_live_one_are_deleted(
        self, db_session: Session, make_user
    ):
        user = make_user()
        live = _make_session(
            db_session,
            user.id,
            created_ago=timedelta(hours=1),
            last_used_ago=timedelta(minutes=2),
        )
        dead = _make_session(
            db_session,
            user.id,
            created_ago=timedelta(days=30),
            last_used_ago=timedelta(days=29),
        )

        housekeeping_jobs.purge_old_request_logs()

        assert _surviving(db_session, [live, dead]) == {live}
