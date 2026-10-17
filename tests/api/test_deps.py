from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import deps
from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    SESSION_IDLE_TIMEOUT_MINUTES,
    create_access_token,
)
from app.db.models.personal_access_token import PersonalAccessToken


def test_expired_idle_session_is_rejected_and_deleted(client, make_user, db_session):
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    session_row = result.scalar_one()
    session_row.last_used_at = datetime.now(UTC) - timedelta(
        minutes=SESSION_IDLE_TIMEOUT_MINUTES + 1
    )
    db_session.commit()

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Session wegen Inaktivität abgelaufen."

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    assert result.scalar_one_or_none() is None


def test_invalid_bearer_token_is_rejected(client):
    response = client.post(
        "/auth/logout", headers={"Authorization": "Bearer not-a-real-jwt"}
    )

    assert response.status_code == 401


def test_unknown_session_token_is_rejected(client, make_user):
    user = make_user()
    token, _jti = create_access_token(
        subject=user.email, jti_override="never-persisted"
    )

    response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_deleted_user_is_rejected_despite_valid_session(client, make_user, db_session):
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    user.deleted_at = datetime.now(UTC)
    db_session.commit()

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401


def test_token_missing_claims_is_rejected(client):
    """A syntactically valid, correctly-signed JWT that is nonetheless
    missing `sub`/`jti` must be rejected -- defensive guard against a
    malformed/foreign token, not something our own create_access_token can
    itself ever produce."""
    token_without_jti = jwt.encode(
        {"sub": "someone@example.test"}, SECRET_KEY, algorithm=ALGORITHM
    )

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {token_without_jti}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten ungültig."


def test_session_with_never_used_timestamp_is_bumped_not_rejected(
    client, make_user, db_session
):
    """`last_used_at` is nullable in the schema even though our own
    create_user_session always sets it -- covers the defensive branch for
    a hypothetically null value rather than assuming it can't happen."""
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    session_row = result.scalar_one()
    session_row.last_used_at = None
    db_session.commit()

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    db_session.refresh(user)
    assert user.auth_lastsignal is not None


def test_session_within_grace_period_bumps_lastsignal(client, make_user, db_session):
    """Between 1 minute and the idle timeout, activity is recorded
    (last_used_at/auth_lastsignal bumped) but the session is NOT
    invalidated -- covers the "still active, just quiet" branch, distinct
    from both the sub-1-minute no-op and the over-timeout rejection."""
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    session_row = result.scalar_one()
    session_row.last_used_at = datetime.now(UTC) - timedelta(minutes=2)
    db_session.commit()

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    db_session.refresh(user)
    assert user.auth_lastsignal is not None


def test_session_used_within_the_last_minute_does_not_bump_lastsignal(
    client, make_user, db_session
):
    """Sub-1-minute activity is a deliberate no-op, the mirror image of the
    grace-period test above -- same DB-write-avoidance throttle
    PersonalAccessToken.last_used_at's own bump uses (see
    _enforce_idle_timeout). auth_lastsignal is seeded with a distinguishable
    stale value first, so "unchanged" can't be confused with "never set"."""
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    stale_lastsignal = datetime.now(UTC) - timedelta(hours=1)
    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    session_row = result.scalar_one()
    session_row.last_used_at = datetime.now(UTC) - timedelta(seconds=30)
    user.auth_lastsignal = stale_lastsignal
    db_session.commit()

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    db_session.refresh(user)
    assert user.auth_lastsignal == stale_lastsignal


def test_token_without_expiry_is_rejected(client, make_user, db_session):
    """Signed, bound to a live session, but without an exp claim: such a
    token would never expire on its own."""
    user = make_user(password="correct-password")
    client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    session_row = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    ).scalar_one()
    token_without_exp = jwt.encode(
        {"sub": user.email, "jti": session_row.token},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {token_without_exp}"}
    )

    assert response.status_code == 401


def test_session_of_another_user_does_not_authenticate_the_subject(
    client, make_user, db_session
):
    """The JWT subject is an e-mail address. A token naming user B but
    carrying the session id (jti) of user A's session must be rejected."""
    user_a = make_user(password="correct-password")
    user_b = make_user()
    client.post(
        "/auth/login",
        data={"username": user_a.email, "password": "correct-password"},
    )
    session_a = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user_a.id)
    ).scalar_one()
    forged_token, _jti = create_access_token(
        subject=user_b.email, jti_override=session_a.token
    )

    response = client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {forged_token}"}
    )

    assert response.status_code == 401


def test_each_rejected_token_raises_its_own_exception_object(db_session):
    """A shared exception object would collect the traceback of every failed
    request and grow without bound, so each rejection must raise a new one."""
    with pytest.raises(HTTPException) as first:
        deps.get_current_user("not-a-jwt", db_session)
    with pytest.raises(HTTPException) as second:
        deps.get_current_user("not-a-jwt", db_session)

    assert first.value is not second.value
    assert first.value.status_code == 401
    assert second.value.status_code == 401


def test_current_session_id_is_the_jti_of_the_token():
    token, session_id = create_access_token(subject="someone@example.com")

    assert deps.get_current_session_id(token) == session_id


def test_current_session_id_rejects_an_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_session_id("not-a-jwt")

    assert exc_info.value.status_code == 401
