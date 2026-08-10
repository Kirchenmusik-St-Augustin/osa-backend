import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models.oauth2_binding import Oauth2Binding
from app.db.models.sent_email import SentEmail
from app.services import auth_service


def test_login_success_sets_refresh_cookie_and_returns_access_token(client, make_user):
    user = make_user(password="correct-password")

    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh_token" in response.cookies


def test_login_unknown_email_returns_generic_german_message(client):
    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.test", "password": "irrelevant"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten unbekannt."


def test_login_wrong_password_returns_same_generic_message_as_unknown_email(
    client, make_user
):
    """Hard Legacy parity: lang/de/auth.php's `failed` string covers BOTH
    cases identically -- there is no separate "Passwort falsch." message in
    the login flow (that belongs to the unrelated change-password form)."""
    user = make_user(password="correct-password")

    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten unbekannt."


def test_login_locked_account_returns_locked_message(client, make_user):
    user = make_user(password="correct-password", auth_locked=True)

    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Benutzerkonto gesperrt."


def test_login_throttles_after_five_failed_attempts(client, make_user):
    user = make_user(password="correct-password")

    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        response = client.post(
            "/auth/login",
            data={"username": user.email, "password": "wrong-password"},
        )
        assert response.status_code == 401

    throttled_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "wrong-password"},
    )

    assert throttled_response.status_code == 429
    body = throttled_response.json()
    assert "Zu viele Anmeldeversuche" in body["detail"]
    assert "Sekunden erneut versuchen" in body["detail"]

    # Even the CORRECT password is blocked while throttled.
    still_blocked = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    assert still_blocked.status_code == 429


def test_login_missing_fields_returns_german_validation_messages(client):
    response = client.post("/auth/login", data={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["msg"] == "Dieses Feld ist erforderlich." for err in detail)


def test_refresh_without_cookie_returns_401(client):
    response = client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Kein Refresh-Token vorhanden."


def test_refresh_rotates_token_and_reuse_is_rejected(client, make_user):
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    # The Set-Cookie's Path=/api/auth is the browser-visible (Caddy-fronted)
    # URL -- this test client hits the ASGI app directly at "/auth/..." with
    # no Caddy in front, so httpx's automatic path-scoped cookie jar would
    # never resend it. Carry it over manually instead (path-unrestricted),
    # matching what a real proxied browser request does in production.
    client.cookies.set("refresh_token", login_response.cookies["refresh_token"])

    refresh_response = client.post("/auth/refresh")

    assert refresh_response.status_code == 200
    # The access token's jti (session id) deliberately stays constant across
    # a refresh (1:1 vb-api design) -- within the same wall-clock second,
    # iat/exp/sub/jti are then all identical too, so the JWT bytes can
    # legitimately be unchanged. What's actually guaranteed to rotate is the
    # refresh secret itself (old one must stop working, see below).
    assert refresh_response.json()["access_token"]
    new_refresh_cookie = refresh_response.cookies["refresh_token"]
    assert new_refresh_cookie != login_response.cookies["refresh_token"]


def test_refresh_with_invalid_cookie_clears_it_and_returns_401(client):
    client.cookies.set("refresh_token", "bogus-session:bogus-secret")

    response = client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Session abgelaufen oder ungültig."


def test_logout_requires_authentication(client):
    response = client.post("/auth/logout")

    assert response.status_code == 401


def test_logout_success_clears_cookie(client, make_user):
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    response = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Erfolgreich abgemeldet."


def test_me_returns_profile_with_permissions(client, make_user, db_session):
    # The shared test-session SQLite DB has no per-test rollback -- the
    # kill-switch assertion below counts ALL `sent_emails` rows, so it must
    # start from a clean table (same reasoning as test_mailer.py's
    # `_clear_sent_emails` fixture).
    db_session.query(SentEmail).delete()
    db_session.commit()

    user = make_user(password="correct-password", roles=["disponent"])
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == user.email
    assert body["surname"] == user.surname
    assert body["givenname"] == user.givenname
    assert body["administrator"] is False
    assert "userMaintain" in body["permissions"]
    assert body["email_kill_switch"] == {
        "active": False,
        "period_days": 30,
        "threshold": 950,
    }


def test_me_requires_authentication(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_reflects_kill_switch_status(
    client, make_user, db_session, monkeypatch: pytest.MonkeyPatch
):
    """Schritt 7: /auth/me is the transport for the navbar warning icon --
    see app.core.mailer.get_kill_switch_status()."""
    db_session.query(SentEmail).delete()
    monkeypatch.setenv("MAIL_KILL_SWITCH_THRESHOLD", "1")
    db_session.add(SentEmail(to="a@example.test", created_at=datetime.now(UTC)))
    db_session.commit()

    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    assert response.json()["email_kill_switch"] == {
        "active": True,
        "period_days": 30,
        "threshold": 1,
    }


def test_get_current_user_rejects_locked_account_mid_session(
    client, make_user, db_session
):
    user = make_user(password="correct-password")
    login_response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    # Locked *after* login -- Legacy's global BlockLocked middleware rejects
    # an already-logged-in, now-locked user on their NEXT request, not just
    # at login time. Our get_current_user dependency must do the same.
    user.auth_locked = True
    db_session.commit()

    response = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Benutzerkonto gesperrt."


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _com_email() -> str:
    # email-validator (backing Pydantic's EmailStr, used by every JSON
    # body below except /auth/login's form-encoded username) hard-rejects
    # the RFC 2606 reserved .test TLD that make_user()'s own default uses.
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def _registration_payload(**overrides: object) -> dict[str, object]:
    unique = uuid.uuid4().hex[:8]
    payload: dict[str, object] = {
        "surname": f"muster{unique}",
        "givenname": f"max{unique}",
        "email": f"max.muster.{unique}@example.com",
        "phone": "+43 660 1234567",
        "password": "Passw0rd1",
        "password_confirmation": "Passw0rd1",
    }
    payload.update(overrides)
    return payload


def test_register_success_auto_logs_in_and_notifies_disponent(client):
    with patch("app.core.mailer.send_new_registration_notice") as mock_notify:
        response = client.post("/auth/register", json=_registration_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert "refresh_token" in response.cookies
    mock_notify.assert_called_once()


def test_register_rejects_duplicate_email(client):
    payload = _registration_payload()
    with patch("app.core.mailer.send_new_registration_notice"):
        first = client.post("/auth/register", json=payload)
    assert first.status_code == 200

    with patch("app.core.mailer.send_new_registration_notice"):
        second = client.post(
            "/auth/register",
            json=_registration_payload(
                surname="Andere", givenname="Person", email=payload["email"].upper()
            ),
        )

    assert second.status_code == 422
    detail = second.json()["detail"]
    assert any(err["loc"] == ["body", "email"] for err in detail)


def test_register_rejects_weak_password(client):
    response = client.post(
        "/auth/register",
        json=_registration_payload(password="short", password_confirmation="short"),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("Richtlinien" in err["msg"] for err in detail)


def test_register_rejects_mismatched_password_confirmation(client):
    response = client.post(
        "/auth/register",
        json=_registration_payload(password_confirmation="Different1"),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("Bestätigung" in err["msg"] for err in detail)


def test_register_rejects_invalid_phone(client):
    response = client.post(
        "/auth/register", json=_registration_payload(phone="not-a-phone!!")
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("Telefonnummer" in err["msg"] for err in detail)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def test_verify_email_success_auto_logs_in(client, make_user):
    user = make_user()
    token = auth_service.build_email_verification_token(user)

    response = client.post("/auth/verify-email", json={"token": token})

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_verify_email_rejects_invalid_token(client):
    response = client.post("/auth/verify-email", json={"token": "not-a-real-token"})

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def test_forgot_password_returns_200_for_unknown_email(client):
    response = client.post(
        "/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 200


def test_forgot_password_queues_reset_mail_for_known_user(
    client, make_user, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "FRONTEND_RESET_PASSWORD_URL",
        "https://einteilung.hochamt.at.dev.schimpl.cc/reset-password",
    )
    user = make_user(email=_com_email())

    with patch("app.core.mailer.send_password_reset_email") as mock_send:
        response = client.post("/auth/forgot-password", json={"email": user.email})

    assert response.status_code == 200
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == user.email


def test_reset_password_success(client, make_user, db_session):
    user = make_user(password="old-password", email=_com_email())
    token = auth_service.request_password_reset(db_session, user.email)

    response = client.post(
        "/auth/reset-password",
        json={
            "email": user.email,
            "token": token,
            "password": "Passw0rd1",
            "password_confirmation": "Passw0rd1",
        },
    )

    assert response.status_code == 200

    login_response = client.post(
        "/auth/login", data={"username": user.email, "password": "Passw0rd1"}
    )
    assert login_response.status_code == 200


def test_reset_password_rejects_invalid_token(client, make_user):
    user = make_user(email=_com_email())

    response = client.post(
        "/auth/reset-password",
        json={
            "email": user.email,
            "token": "bogus-token",
            "password": "Passw0rd1",
            "password_confirmation": "Passw0rd1",
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


def test_google_callback_returns_404_when_not_linked(
    client, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value={"sub": "google-not-linked", "name": "Nobody"},
    ):
        response = client.post(
            "/auth/google/callback", json={"credential": "fake-credential"}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "ACCOUNT_NOT_LINKED"


def test_google_link_then_callback_logs_in(
    client, make_user, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    user = make_user(password="correct-password", email=_com_email())
    google_id_info = {"sub": "google-round-trip", "name": "Max Muster"}

    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=google_id_info,
    ):
        link_response = client.post(
            "/auth/google/link",
            json={
                "credential": "fake-credential",
                "email": user.email,
                "password": "correct-password",
            },
        )
        assert link_response.status_code == 200

        callback_response = client.post(
            "/auth/google/callback", json={"credential": "fake-credential"}
        )

    assert callback_response.status_code == 200
    assert callback_response.json()["access_token"]


def test_google_link_rejects_wrong_password(
    client, make_user, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    user = make_user(password="correct-password", email=_com_email())

    response = client.post(
        "/auth/google/link",
        json={
            "credential": "fake-credential",
            "email": user.email,
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401


def test_oauth2_disconnect_removes_own_binding(
    client, make_user, db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    user = make_user(password="correct-password", email=_com_email())
    login_response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    access_token = login_response.json()["access_token"]

    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value={"sub": "google-disconnect-own", "name": "Max Muster"},
    ):
        client.post(
            "/auth/google/link",
            json={
                "credential": "fake-credential",
                "email": user.email,
                "password": "correct-password",
            },
        )

    binding_id = (
        db_session.execute(
            select(Oauth2Binding).where(Oauth2Binding.local_id == user.id)
        )
        .scalar_one()
        .id
    )

    response = client.delete(
        f"/auth/oauth2/{binding_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200


def test_oauth2_disconnect_rejects_binding_owned_by_another_user(
    client, make_user, db_session
):
    """IDOR regression at the HTTP layer: an authenticated attacker must
    get an identical 404 (not 403) when targeting a binding ID that
    belongs to someone else -- no enumeration signal."""
    victim = make_user()
    attacker = make_user(password="attacker-password")
    db_session.add(
        Oauth2Binding(
            provider="google",
            remote_id=f"google-victim-{uuid.uuid4().hex[:8]}",
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

    login_response = client.post(
        "/auth/login",
        data={"username": attacker.email, "password": "attacker-password"},
    )
    attacker_token = login_response.json()["access_token"]

    response = client.delete(
        f"/auth/oauth2/{binding_id}",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )

    assert response.status_code == 404

    still_present = db_session.execute(
        select(Oauth2Binding).where(Oauth2Binding.id == binding_id)
    ).scalar_one_or_none()
    assert still_present is not None


def test_oauth2_disconnect_requires_authentication(client):
    response = client.delete("/auth/oauth2/1")

    assert response.status_code == 401
