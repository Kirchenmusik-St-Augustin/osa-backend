"""Behaviour that depends on real commits. The ordinary tests run inside one
outer transaction, where a commit only releases a savepoint, so they cannot
tell a committed change from one that a later rollback would have removed.
These tests commit for real (committed_db) and read the result through a
second connection."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash, verify_password
from app.db.models.booking_log import BookingLog
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.user import User
from app.schemas.profile import ProfileUpdateRequest
from app.services import auth_service, booking_jobs, profile_service
from tests import booking_helpers
from tests.conftest import TestingSessionLocal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_CURRENT_PASSWORD = "Passwort123"
_NEW_PASSWORD = "EinNeuesPassw0rt"


def _verified_user(session: Session) -> User:
    user = User(
        surname="Muster",
        givenname=f"Test-{uuid.uuid4().hex[:8]}",
        email=f"{booking_helpers.unique('user')}@example.test",
        auth_password=get_password_hash(_CURRENT_PASSWORD),
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    session.commit()
    return user


class TestNotificationJobCommits:
    def _users_with_unnotified_booking(
        self, session: Session, count: int
    ) -> list[User]:
        users = [_verified_user(session) for _ in range(count)]
        for user in users:
            session.add(
                BookingLog(
                    performance_id=booking_helpers.create_performance(session),
                    user_id=user.id,
                    booking_type="book",
                    instrument_id=booking_helpers.create_instrument(session).id,
                    fee=80,
                )
            )
        session.commit()
        return users

    @staticmethod
    def _notified_user_ids() -> set[uuid.UUID]:
        """Read through a second connection: only committed rows are seen."""
        with TestingSessionLocal() as other:
            return {
                log.user_id
                for log in other.execute(select(BookingLog)).scalars()
                if log.notified_at is not None
            }

    def test_every_notification_is_committed_by_a_complete_run(self, committed_db):
        users = self._users_with_unnotified_booking(committed_db, 2)

        with patch("app.core.mailer.send_booking_status_email"):
            booking_jobs.notify_upcoming_booking_status()

        assert self._notified_user_ids() == {user.id for user in users}

    def test_a_failing_mail_keeps_the_notifications_committed_before_it(
        self, committed_db
    ):
        users = self._users_with_unnotified_booking(committed_db, 2)
        recipients = {user.email: user.id for user in users}
        mailed: list[uuid.UUID] = []

        def fail_on_the_second(to_email: str, _entries: object) -> None:
            if to_email not in recipients:
                return
            if mailed:
                msg = "smtp refused"
                raise RuntimeError(msg)
            mailed.append(recipients[to_email])

        with (
            patch("app.core.mailer.send_booking_status_email", fail_on_the_second),
            pytest.raises(RuntimeError, match="smtp refused"),
        ):
            booking_jobs.notify_upcoming_booking_status()

        assert self._notified_user_ids() == set(mailed)
        assert len(mailed) == 1


class TestPasswordChangeCommits:
    def _request(self) -> ProfileUpdateRequest:
        return ProfileUpdateRequest(
            surname="Muster",
            givenname="Given",
            email=f"{booking_helpers.unique('user')}@example.com",
            phone="+43 660 1234567",
            change_password=True,
            password=_NEW_PASSWORD,
            password_confirmation=_NEW_PASSWORD,
            auth_password=_CURRENT_PASSWORD,
        )

    def _user_with_two_sessions(self, session: Session) -> tuple[User, str, str]:
        user = _verified_user(session)
        _token, own_session, _secret = auth_service.create_user_session(session, user)
        _token, other_session, _secret = auth_service.create_user_session(session, user)
        return user, own_session, other_session

    @staticmethod
    def _stored(user_id: uuid.UUID) -> tuple[str, set[str]]:
        """Password hash and session ids as a second connection sees them."""
        with TestingSessionLocal() as other:
            stored_user = other.get(User, user_id)
            assert stored_user is not None
            sessions = set(
                other.execute(
                    select(PersonalAccessToken.jti).where(
                        PersonalAccessToken.user_id == user_id
                    )
                ).scalars()
            )
            return stored_user.auth_password, sessions

    def test_the_new_password_and_the_revocation_are_committed_together(
        self, committed_db
    ):
        user, own_session, _other_session = self._user_with_two_sessions(committed_db)

        profile_service.update_profile(
            committed_db, user, self._request(), current_session_id=own_session
        )

        password_hash, sessions = self._stored(user.id)
        assert verify_password(_NEW_PASSWORD, password_hash)
        assert sessions == {own_session}

    def test_a_failed_commit_leaves_the_password_and_every_session_untouched(
        self, committed_db, monkeypatch: pytest.MonkeyPatch
    ):
        """The e-mail address is taken between the check and the commit, so
        the commit itself fails after the password was set and the other
        sessions were deleted: nothing of it may stay."""
        user, own_session, other_session = self._user_with_two_sessions(committed_db)
        user_id = user.id
        competitor = _verified_user(committed_db)
        request = self._request().model_copy(update={"email": competitor.email})
        monkeypatch.setattr(
            profile_service, "_email_taken", lambda *_args, **_kwargs: False
        )

        with pytest.raises(IntegrityError):
            profile_service.update_profile(
                committed_db, user, request, current_session_id=own_session
            )
        committed_db.rollback()

        password_hash, sessions = self._stored(user_id)
        assert verify_password(_CURRENT_PASSWORD, password_hash)
        assert sessions == {own_session, other_session}
