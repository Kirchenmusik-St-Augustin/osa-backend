from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    hash_refresh_secret,
)
from app.db.models.auth_log import AuthLog
from app.db.models.personal_access_token import PersonalAccessToken
from app.services import auth_service
from app.services.auth_service import InvalidSessionError

pytestmark = pytest.mark.usefixtures("db_session")


def test_authenticate_user_unknown_email(db_session):
    user, reason = auth_service.authenticate_user(
        db_session, "nobody@example.test", "irrelevant"
    )

    assert user is None
    assert reason == "unknown_email"


def test_authenticate_user_wrong_password(db_session, make_user):
    created = make_user(password="correct-password")

    user, reason = auth_service.authenticate_user(
        db_session, created.email, "wrong-password"
    )

    assert user is None
    assert reason == "wrong_password"


def test_authenticate_user_account_locked(db_session, make_user):
    created = make_user(password="correct-password", auth_locked=True)

    user, reason = auth_service.authenticate_user(
        db_session, created.email, "correct-password"
    )

    assert user is None
    assert reason == "account_locked"


def test_authenticate_user_success(db_session, make_user):
    created = make_user(password="correct-password")

    user, reason = auth_service.authenticate_user(
        db_session, created.email, "correct-password"
    )

    assert user is not None
    assert user.id == created.id
    assert reason == "ok"


def test_authenticate_user_email_match_is_case_sensitive(db_session, make_user):
    make_user(email="CaseSensitive@example.test", password="pw")

    user, reason = auth_service.authenticate_user(
        db_session, "casesensitive@example.test", "pw"
    )

    assert user is None
    assert reason == "unknown_email"


def test_check_login_throttle_allows_under_threshold(db_session, make_user):
    created = make_user()
    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS - 1):
        auth_service.log_auth_event(
            db_session, "Failed", created.email, ip_address="1.2.3.4"
        )

    result = auth_service.check_login_throttle(
        db_session, created.email, ip_address="1.2.3.4"
    )

    assert result is None


def test_check_login_throttle_blocks_at_threshold(db_session, make_user):
    created = make_user()
    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        auth_service.log_auth_event(
            db_session, "Failed", created.email, ip_address="1.2.3.4"
        )

    result = auth_service.check_login_throttle(
        db_session, created.email, ip_address="1.2.3.4"
    )

    assert result is not None
    assert 0 < result <= auth_service.LOGIN_THROTTLE_WINDOW_SECONDS


def test_check_login_throttle_is_scoped_per_ip(db_session, make_user):
    created = make_user()
    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        auth_service.log_auth_event(
            db_session, "Failed", created.email, ip_address="1.2.3.4"
        )

    result = auth_service.check_login_throttle(
        db_session, created.email, ip_address="9.9.9.9"
    )

    assert result is None


def test_check_login_throttle_clears_after_success(db_session, make_user):
    created = make_user()
    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        auth_service.log_auth_event(
            db_session, "Failed", created.email, ip_address="1.2.3.4"
        )
    auth_service.log_auth_event(
        db_session, "Login", created.email, ip_address="1.2.3.4"
    )

    result = auth_service.check_login_throttle(
        db_session, created.email, ip_address="1.2.3.4"
    )

    assert result is None


def test_check_login_throttle_ignores_failures_outside_window(db_session, make_user):
    created = make_user()
    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        db_session.add(
            AuthLog(
                event="Failed",
                fired_at=datetime.now(UTC)
                - timedelta(seconds=auth_service.LOGIN_THROTTLE_WINDOW_SECONDS + 5),
                ip_address="1.2.3.4",
                email=created.email,
                payload={},
            )
        )
    db_session.commit()

    result = auth_service.check_login_throttle(
        db_session, created.email, ip_address="1.2.3.4"
    )

    assert result is None


def test_create_user_session_persists_token_and_lastlogin(db_session, make_user):
    created = make_user()

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    assert access_token
    assert session_id
    assert refresh_secret

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == session_id)
    )
    token_row = result.scalar_one()
    assert token_row.user_id == created.id
    assert token_row.refresh_token_hash == hash_refresh_secret(refresh_secret)

    db_session.refresh(created)
    assert created.auth_lastlogin is not None


def test_create_user_session_rejects_user_without_email(db_session, make_user):
    created = make_user()
    created.email = None

    with pytest.raises(ValueError, match="keine E-Mail-Adresse"):
        auth_service.create_user_session(db_session, created)


def test_refresh_session_rotates_secret(db_session, make_user):
    created = make_user()
    _access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    new_access_token, new_secret = auth_service.refresh_session(
        db_session, session_id, refresh_secret
    )

    assert new_access_token
    assert new_secret != refresh_secret

    # Old secret must no longer verify -- it was rotated, not reused.
    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, refresh_secret)


def test_refresh_session_rejects_unknown_session(db_session):
    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, "no-such-session", "whatever")


def test_refresh_session_rejects_wrong_secret(db_session, make_user):
    created = make_user()
    _access_token, session_id, _refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, "wrong-secret")


def test_refresh_session_rejects_idle_timeout(db_session, make_user):
    created = make_user()
    _access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == session_id)
    )
    token_row = result.scalar_one()
    token_row.last_used_at = datetime.now(UTC) - timedelta(hours=999)
    db_session.commit()

    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, refresh_secret)


def test_refresh_session_rejects_absolute_lifetime_exceeded(db_session, make_user):
    created = make_user()
    _access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == session_id)
    )
    token_row = result.scalar_one()
    token_row.created_at = datetime.now(UTC) - timedelta(days=999)
    db_session.commit()

    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, refresh_secret)


def test_refresh_session_rejects_user_without_email(db_session, make_user):
    created = make_user()
    _access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )
    created.email = None
    db_session.commit()

    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, refresh_secret)


def test_refresh_session_rejects_locked_account(db_session, make_user):
    created = make_user()
    _access_token, session_id, refresh_secret = auth_service.create_user_session(
        db_session, created
    )
    created.auth_locked = True
    db_session.commit()

    with pytest.raises(InvalidSessionError):
        auth_service.refresh_session(db_session, session_id, refresh_secret)


def test_logout_user_deletes_session_and_sets_lastlogout(db_session, make_user):
    created = make_user()
    access_token, session_id, _refresh_secret = auth_service.create_user_session(
        db_session, created
    )

    auth_service.logout_user(db_session, access_token)

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == session_id)
    )
    assert result.scalar_one_or_none() is None

    db_session.refresh(created)
    assert created.auth_lastlogout is not None


def test_logout_user_ignores_garbage_token(db_session):
    # Must not raise -- Legacy's logout() is a best-effort cleanup.
    auth_service.logout_user(db_session, "not-a-real-jwt")


def test_logout_user_ignores_token_without_jti(db_session):
    token_without_jti = jwt.encode(
        {"sub": "someone@example.test"}, SECRET_KEY, algorithm=ALGORITHM
    )

    # Must not raise -- same best-effort semantics as a garbage token.
    auth_service.logout_user(db_session, token_without_jti)


def test_logout_user_ignores_unknown_session(db_session, make_user):
    created = make_user()
    access_token, _session_id, _refresh_secret = auth_service.create_user_session(
        db_session, created
    )
    # Already-deleted session (e.g. double logout) must be a silent no-op.
    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == created.id)
    )
    db_session.delete(result.scalar_one())
    db_session.commit()

    auth_service.logout_user(db_session, access_token)


def test_log_auth_event_persists_row(db_session):
    auth_service.log_auth_event(
        db_session,
        "Login",
        "someone@example.test",
        ip_address="1.2.3.4",
        user_agent="pytest-agent",
        payload={"foo": "bar"},
    )

    result = db_session.execute(
        select(AuthLog).where(AuthLog.email == "someone@example.test")
    )
    row = result.scalar_one()
    assert row.event == "Login"
    assert row.ip_address == "1.2.3.4"
    assert row.user_agent == "pytest-agent"
    assert row.payload == {"foo": "bar"}
    assert row.fired_at is not None
