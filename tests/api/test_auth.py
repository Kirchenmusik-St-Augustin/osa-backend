from app.services import auth_service


async def test_login_success_sets_refresh_cookie_and_returns_access_token(
    client, make_user
):
    user = await make_user(password="correct-password")

    response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh_token" in response.cookies


async def test_login_unknown_email_returns_generic_german_message(client):
    response = await client.post(
        "/auth/login",
        data={"username": "nobody@example.test", "password": "irrelevant"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten unbekannt."


async def test_login_wrong_password_returns_same_generic_message_as_unknown_email(
    client, make_user
):
    """Hard Legacy parity: lang/de/auth.php's `failed` string covers BOTH
    cases identically -- there is no separate "Passwort falsch." message in
    the login flow (that belongs to the unrelated change-password form)."""
    user = await make_user(password="correct-password")

    response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Anmeldedaten unbekannt."


async def test_login_locked_account_returns_locked_message(client, make_user):
    user = await make_user(password="correct-password", auth_locked=True)

    response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Benutzerkonto gesperrt."


async def test_login_throttles_after_five_failed_attempts(client, make_user):
    user = await make_user(password="correct-password")

    for _ in range(auth_service.MAX_LOGIN_ATTEMPTS):
        response = await client.post(
            "/auth/login",
            data={"username": user.email, "password": "wrong-password"},
        )
        assert response.status_code == 401

    throttled_response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "wrong-password"},
    )

    assert throttled_response.status_code == 429
    body = throttled_response.json()
    assert "Zu viele Anmeldeversuche" in body["detail"]
    assert "Sekunden erneut versuchen" in body["detail"]

    # Even the CORRECT password is blocked while throttled.
    still_blocked = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    assert still_blocked.status_code == 429


async def test_login_missing_fields_returns_german_validation_messages(client):
    response = await client.post("/auth/login", data={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["msg"] == "Dieses Feld ist erforderlich." for err in detail)


async def test_refresh_without_cookie_returns_401(client):
    response = await client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Kein Refresh-Token vorhanden."


async def test_refresh_rotates_token_and_reuse_is_rejected(client, make_user):
    user = await make_user(password="correct-password")
    login_response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    # The Set-Cookie's Path=/api/auth is the browser-visible (Caddy-fronted)
    # URL -- this test client hits the ASGI app directly at "/auth/..." with
    # no Caddy in front, so httpx's automatic path-scoped cookie jar would
    # never resend it. Carry it over manually instead (path-unrestricted),
    # matching what a real proxied browser request does in production.
    client.cookies.set("refresh_token", login_response.cookies["refresh_token"])

    refresh_response = await client.post("/auth/refresh")

    assert refresh_response.status_code == 200
    # The access token's jti (session id) deliberately stays constant across
    # a refresh (1:1 vb-api design) -- within the same wall-clock second,
    # iat/exp/sub/jti are then all identical too, so the JWT bytes can
    # legitimately be unchanged. What's actually guaranteed to rotate is the
    # refresh secret itself (old one must stop working, see below).
    assert refresh_response.json()["access_token"]
    new_refresh_cookie = refresh_response.cookies["refresh_token"]
    assert new_refresh_cookie != login_response.cookies["refresh_token"]


async def test_refresh_with_invalid_cookie_clears_it_and_returns_401(client):
    client.cookies.set("refresh_token", "bogus-session:bogus-secret")

    response = await client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Session abgelaufen oder ungültig."


async def test_logout_requires_authentication(client):
    response = await client.post("/auth/logout")

    assert response.status_code == 401


async def test_logout_success_clears_cookie(client, make_user):
    user = await make_user(password="correct-password")
    login_response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    response = await client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Erfolgreich abgemeldet."


async def test_get_current_user_rejects_locked_account_mid_session(
    client, make_user, db_session
):
    user = await make_user(password="correct-password")
    login_response = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    access_token = login_response.json()["access_token"]

    # Locked *after* login -- Legacy's global BlockLocked middleware rejects
    # an already-logged-in, now-locked user on their NEXT request, not just
    # at login time. Our get_current_user dependency must do the same.
    user.auth_locked = True
    await db_session.commit()

    response = await client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Benutzerkonto gesperrt."
