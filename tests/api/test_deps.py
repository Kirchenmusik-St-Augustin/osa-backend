from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    SESSION_IDLE_TIMEOUT_MINUTES,
    create_access_token,
)
from app.db.models.personal_access_token import PersonalAccessToken


async def test_expired_idle_session_is_rejected_and_deleted(
    client, make_user, db_session
):
    user = make_user(password="correct-password")
    login_response = await client.post(
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

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Session wegen Inaktivität abgelaufen."

    result = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    assert result.scalar_one_or_none() is None


async def test_invalid_bearer_token_is_rejected(client):
    response = await client.post(
        "/auth/logout", headers={"Authorization": "Bearer not-a-real-jwt"}
    )

    assert response.status_code == 401


async def test_unknown_session_token_is_rejected(client, make_user):
    user = make_user()
    token, _jti = create_access_token(
        subject=user.email, jti_override="never-persisted"
    )

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_deleted_user_is_rejected_despite_valid_session(
    client, make_user, db_session
):
    user = make_user(password="correct-password")
    login_response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    user.deleted_at = datetime.now(UTC)
    db_session.commit()

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401


async def test_token_missing_claims_is_rejected(client):
    """A syntactically valid, correctly-signed JWT that is nonetheless
    missing `sub`/`jti` must be rejected -- defensive guard against a
    malformed/foreign token, not something our own create_access_token can
    itself ever produce."""
    token_without_jti = jwt.encode(
        {"sub": "someone@example.test"}, SECRET_KEY, algorithm=ALGORITHM
    )

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {token_without_jti}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten ungültig."


async def test_session_with_never_used_timestamp_is_bumped_not_rejected(
    client, make_user, db_session
):
    """`last_used_at` is nullable in the schema even though our own
    create_user_session always sets it -- covers the defensive branch for
    a hypothetically null value rather than assuming it can't happen."""
    user = make_user(password="correct-password")
    login_response = await client.post(
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

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200


async def test_session_within_grace_period_bumps_lastsignal(
    client, make_user, db_session
):
    """Between 1 minute and the idle timeout, activity is recorded
    (last_used_at/auth_lastsignal bumped) but the session is NOT
    invalidated -- covers the "still active, just quiet" branch, distinct
    from both the sub-1-minute no-op and the over-timeout rejection."""
    user = make_user(password="correct-password")
    login_response = await client.post(
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

    response = await client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
