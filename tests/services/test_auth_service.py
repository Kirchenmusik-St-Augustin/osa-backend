import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy import select

from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    create_email_verification_token,
    hash_refresh_secret,
    hash_reset_token,
)
from app.db.models.auth_log import AuthLog
from app.db.models.oauth2_binding import Oauth2Binding
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.personal_access_token import PersonalAccessToken
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from app.services.auth_service import (
    AccountNotLinkedError,
    InvalidSessionError,
    OauthBindingNotFoundError,
    RegistrationConflictError,
)

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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _register_request(**overrides: object) -> RegisterRequest:
    """Every field defaults to a fresh unique value per call -- the test
    DB is a single shared SQLite file for the whole test run (no per-test
    transaction rollback), so fixed literals would collide with rows a
    different test already committed (unique constraints on email and on
    the surname+givenname combo)."""
    # email-validator (backing Pydantic's EmailStr) hard-rejects the
    # RFC 2606 reserved TLDs .test/.invalid/.localhost used everywhere
    # else in this suite -- "example.com" is the one reserved-for-docs
    # domain it still accepts syntactically.
    unique = uuid.uuid4().hex[:8]
    defaults: dict[str, object] = {
        "surname": f"muster{unique}",
        "givenname": f"max{unique}",
        "email": f"max.muster.{unique}@example.com",
        "phone": "+43 660 1234567",
        "password": "Passw0rd1",
        "password_confirmation": "Passw0rd1",
    }
    defaults.update(overrides)
    return RegisterRequest(**defaults)


def test_register_user_persists_normalized_fields(db_session):
    request = _register_request(surname="muster", givenname="max")

    user = auth_service.register_user(db_session, request)

    assert user.surname == "MUSTER"
    assert user.givenname == "Max"
    assert user.email == request.email
    assert user.auth_password != "Passw0rd1"


def test_register_user_rejects_duplicate_name_combo_case_insensitive(db_session):
    unique = uuid.uuid4().hex[:8]
    existing = auth_service.register_user(
        db_session,
        _register_request(surname=f"muster{unique}", givenname=f"max{unique}"),
    )
    assert existing.surname == f"MUSTER{unique}".upper()

    with pytest.raises(RegistrationConflictError) as exc_info:
        auth_service.register_user(
            db_session,
            _register_request(surname=f"MUSTER{unique}", givenname=f"MAX{unique}"),
        )

    fields = {field for field, _msg in exc_info.value.errors}
    assert fields == {"givenname", "surname"}


def test_register_user_rejects_duplicate_email_case_insensitive(db_session):
    request = _register_request()
    auth_service.register_user(db_session, request)

    with pytest.raises(RegistrationConflictError) as exc_info:
        auth_service.register_user(
            db_session,
            _register_request(
                surname="Zweite", givenname="Person", email=request.email.upper()
            ),
        )

    fields = {field for field, _msg in exc_info.value.errors}
    assert fields == {"email"}


def test_register_user_rejects_reusing_soft_deleted_users_identity(
    db_session, make_user
):
    unique = uuid.uuid4().hex[:8]
    deleted_user = make_user(
        email=f"max.muster.{unique}@example.test", password="irrelevant-password"
    )
    deleted_user.surname = f"MUSTER{unique}"
    deleted_user.givenname = f"Max{unique}"
    deleted_user.deleted_at = datetime.now(UTC)
    db_session.commit()

    with pytest.raises(RegistrationConflictError):
        auth_service.register_user(
            db_session,
            _register_request(
                surname=f"muster{unique}",
                givenname=f"max{unique}",
                email=f"other.{unique}@example.com",
            ),
        )


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def test_build_and_verify_email_verification_token_roundtrip(db_session, make_user):
    user = make_user()

    token = auth_service.build_email_verification_token(user)
    verified_user = auth_service.verify_email(db_session, token)

    assert verified_user.id == user.id
    db_session.refresh(user)
    assert user.email_verified_at is not None


def test_verify_email_is_idempotent_on_already_verified_user(db_session, make_user):
    user = make_user()
    token = auth_service.build_email_verification_token(user)
    auth_service.verify_email(db_session, token)
    db_session.refresh(user)
    first_verified_at = user.email_verified_at

    auth_service.verify_email(db_session, token)

    db_session.refresh(user)
    assert user.email_verified_at == first_verified_at


def test_verify_email_rejects_unknown_user_id(db_session):
    token = create_email_verification_token(999_999, "nobody@example.test")

    with pytest.raises(ValueError, match="ungültig oder abgelaufen"):
        auth_service.verify_email(db_session, token)


def test_verify_email_rejects_token_after_email_changed(db_session, make_user):
    user = make_user()
    token = auth_service.build_email_verification_token(user)

    user.email = f"changed.{uuid.uuid4().hex[:8]}@example.test"
    db_session.commit()

    with pytest.raises(ValueError, match="ungültig oder abgelaufen"):
        auth_service.verify_email(db_session, token)


def test_build_email_verification_token_requires_email(db_session, make_user):
    user = make_user()
    user.email = None
    db_session.commit()

    with pytest.raises(ValueError, match="keine E-Mail-Adresse"):
        auth_service.build_email_verification_token(user)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def test_request_password_reset_returns_none_for_unknown_email(db_session):
    assert (
        auth_service.request_password_reset(db_session, "nobody@example.test") is None
    )


def test_request_password_reset_creates_token_row(db_session, make_user):
    user = make_user()

    token = auth_service.request_password_reset(db_session, user.email)

    assert token is not None
    row = db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.email == user.email.lower())
    ).scalar_one()
    assert row.token == hash_reset_token(token)


def test_request_password_reset_replaces_previous_token(db_session, make_user):
    user = make_user()

    first_token = auth_service.request_password_reset(db_session, user.email)
    second_token = auth_service.request_password_reset(db_session, user.email)

    assert first_token != second_token
    rows = (
        db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.email == user.email.lower()
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_execute_password_reset_success_sets_password_and_invalidates_sessions(
    db_session, make_user
):
    user = make_user(password="old-password")
    _access_token, _session_id, _refresh_secret = auth_service.create_user_session(
        db_session, user
    )
    token = auth_service.request_password_reset(db_session, user.email)

    auth_service.execute_password_reset(db_session, user.email, token, "Passw0rd1")

    db_session.refresh(user)
    assert user.email_verified_at is not None
    new_user, reason = auth_service.authenticate_user(
        db_session, user.email, "Passw0rd1"
    )
    assert reason == "ok"
    assert new_user is not None
    # Old session must be gone (reset invalidates all sessions).
    remaining = db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    ).scalar_one_or_none()
    assert remaining is None


def test_execute_password_reset_rejects_invalid_token(db_session, make_user):
    user = make_user()

    with pytest.raises(ValueError, match="ungültig"):
        auth_service.execute_password_reset(
            db_session, user.email, "bogus-token", "Passw0rd1"
        )


def test_execute_password_reset_rejects_expired_token(db_session, make_user):
    user = make_user()
    token = auth_service.request_password_reset(db_session, user.email)
    row = db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.email == user.email.lower())
    ).scalar_one()
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    with pytest.raises(ValueError, match="ungültig"):
        auth_service.execute_password_reset(db_session, user.email, token, "Passw0rd1")


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


def _google_id_info(sub: str | None = None, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "sub": sub or f"google-{uuid.uuid4().hex[:8]}",
        "name": "Max Muster",
    }
    defaults.update(overrides)
    return defaults


def test_authenticate_google_user_raises_when_not_linked(db_session):
    with (
        patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=_google_id_info(),
        ),
        patch("app.services.auth_service.require_setting", return_value="client-id"),
        pytest.raises(AccountNotLinkedError),
    ):
        auth_service.authenticate_google_user(db_session, "fake-credential")


def test_authenticate_google_user_logs_in_when_bound(db_session, make_user):
    user = make_user()
    google_sub = f"google-{uuid.uuid4().hex[:8]}"
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=google_sub,
            remote_name="Max Muster",
            local_id=user.id,
            bound_at=datetime.now(UTC),
            lastuse_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    db_session.commit()

    with (
        patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=_google_id_info(sub=google_sub),
        ),
        patch("app.services.auth_service.require_setting", return_value="client-id"),
    ):
        logged_in_user = auth_service.authenticate_google_user(
            db_session, "fake-credential"
        )

    assert logged_in_user.id == user.id
    assert logged_in_user.auth_lastlogin_provider == "google"


def test_authenticate_google_user_rejects_locked_account(db_session, make_user):
    user = make_user(auth_locked=True)
    google_sub = f"google-{uuid.uuid4().hex[:8]}"
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=google_sub,
            remote_name="Max Muster",
            local_id=user.id,
            bound_at=datetime.now(UTC),
            lastuse_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    with (
        patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=_google_id_info(sub=google_sub),
        ),
        patch("app.services.auth_service.require_setting", return_value="client-id"),
        pytest.raises(ValueError, match="gesperrt"),
    ):
        auth_service.authenticate_google_user(db_session, "fake-credential")


def test_link_google_account_rejects_wrong_local_credentials(db_session, make_user):
    user = make_user(password="correct-password")

    with pytest.raises(ValueError, match="Anmeldedaten unbekannt"):
        auth_service.link_google_account(
            db_session, "fake-credential", user.email, "wrong-password"
        )


def test_link_google_account_creates_new_binding(db_session, make_user):
    user = make_user(password="correct-password")
    google_sub = f"google-{uuid.uuid4().hex[:8]}"

    with (
        patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=_google_id_info(sub=google_sub),
        ),
        patch("app.services.auth_service.require_setting", return_value="client-id"),
    ):
        linked_user = auth_service.link_google_account(
            db_session, "fake-credential", user.email, "correct-password"
        )

    assert linked_user.id == user.id
    binding = db_session.execute(
        select(Oauth2Binding).where(Oauth2Binding.local_id == user.id)
    ).scalar_one()
    assert binding.remote_id == google_sub


def test_link_google_account_rejects_binding_already_used_by_other_account(
    db_session, make_user
):
    other_user = make_user()
    google_sub = f"google-{uuid.uuid4().hex[:8]}"
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=google_sub,
            remote_name="Someone Else",
            local_id=other_user.id,
            bound_at=datetime.now(UTC),
            lastuse_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    user = make_user(password="correct-password")

    with (
        patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=_google_id_info(sub=google_sub),
        ),
        patch("app.services.auth_service.require_setting", return_value="client-id"),
        pytest.raises(ValueError, match="bereits verknüpft"),
    ):
        auth_service.link_google_account(
            db_session, "fake-credential", user.email, "correct-password"
        )


def test_unlink_oauth_binding_removes_owned_binding(db_session, make_user):
    user = make_user()
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=f"google-{uuid.uuid4().hex[:8]}",
            remote_name="Max Muster",
            local_id=user.id,
            bound_at=datetime.now(UTC),
            lastuse_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    binding_id = (
        db_session.execute(
            select(Oauth2Binding).where(Oauth2Binding.local_id == user.id)
        )
        .scalar_one()
        .id
    )

    auth_service.unlink_oauth_binding(db_session, binding_id, user.id)

    remaining = db_session.execute(
        select(Oauth2Binding).where(Oauth2Binding.id == binding_id)
    ).scalar_one_or_none()
    assert remaining is None


def test_unlink_oauth_binding_rejects_binding_owned_by_another_user(
    db_session, make_user
):
    """IDOR regression test: Legacy's `oauth2disconnect($id)` looked up
    the binding by ID alone, with no ownership check at all -- any
    logged-in user could delete any other user's Google link. This must
    now be rejected instead, and rejected the SAME way as a not-found ID
    (uniform 404 at the router level, no enumeration signal)."""
    victim = make_user()
    attacker = make_user()
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=f"google-{uuid.uuid4().hex[:8]}",
            remote_name="Victim",
            local_id=victim.id,
            bound_at=datetime.now(UTC),
            lastuse_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    binding_id = (
        db_session.execute(
            select(Oauth2Binding).where(Oauth2Binding.local_id == victim.id)
        )
        .scalar_one()
        .id
    )

    with pytest.raises(OauthBindingNotFoundError):
        auth_service.unlink_oauth_binding(db_session, binding_id, attacker.id)

    still_present = db_session.execute(
        select(Oauth2Binding).where(Oauth2Binding.id == binding_id)
    ).scalar_one_or_none()
    assert still_present is not None


def test_unlink_oauth_binding_rejects_unknown_id(db_session, make_user):
    user = make_user()

    with pytest.raises(OauthBindingNotFoundError):
        auth_service.unlink_oauth_binding(db_session, 999_999, user.id)
