import uuid

import pytest


def _unique(base: str = "Profile") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, password: str = "Passwort123"
) -> tuple[dict[str, str], str]:
    email = f"{_unique('user').lower()}@example.com"
    user = make_user(email=email, password=password)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


def _payload(
    *, email: str, current_password: str = "Passwort123", **overrides: object
) -> dict:
    # `current_password` (-> auth_password, the re-auth confirmation) is
    # deliberately named differently from the "password" dict key (the NEW
    # password, only relevant when change_password=True) -- overrides pass
    # a real "password" straight through **overrides instead of colliding
    # with this named parameter.
    base = {
        "givenname": "Max",
        "surname": _unique("Muster"),
        "email": email,
        "phone": "+43 660 1234567",
        "change_password": False,
        "password": None,
        "password_confirmation": None,
        "auth_password": current_password,
    }
    base.update(overrides)
    return base


class TestPermissionGuard:
    def test_get_requires_authentication(self, client):
        response = client.get("/profile")
        assert response.status_code == 401

    def test_put_requires_authentication(self, client):
        response = client.put("/profile", json=_payload(email="a@example.com"))
        assert response.status_code == 401


class TestGetProfile:
    def test_returns_own_data(self, client, make_user):
        headers, email = _auth_headers(client, make_user)
        response = client.get("/profile", headers=headers)
        assert response.status_code == 200
        assert response.json()["email"] == email


class TestUpdateProfile:
    def test_updates_fields(self, client, make_user):
        headers, email = _auth_headers(client, make_user)
        new_surname = _unique("Neu")

        response = client.put(
            "/profile",
            json=_payload(email=email, surname=new_surname, phone="+43 664 7654321"),
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["surname"] == new_surname.upper()
        assert response.json()["phone"] == "+43 664 7654321"

    def test_wrong_current_password_returns_422_on_auth_password_field(
        self, client, make_user
    ):
        headers, email = _auth_headers(client, make_user)
        response = client.put(
            "/profile",
            json=_payload(email=email, auth_password="totally-wrong"),
            headers=headers,
        )
        assert response.status_code == 422
        fields = {error["loc"][1] for error in response.json()["detail"]}
        assert fields == {"auth_password"}

    def test_extra_field_is_rejected(self, client, make_user):
        headers, email = _auth_headers(client, make_user)
        response = client.put(
            "/profile",
            json=_payload(email=email, administrator=True),
            headers=headers,
        )
        assert response.status_code == 422

    def test_unchanged_email_sends_no_verification_mail(
        self, client, make_user, fake_arq_pool
    ):
        headers, email = _auth_headers(client, make_user)
        response = client.put("/profile", json=_payload(email=email), headers=headers)
        assert response.status_code == 200
        fake_arq_pool.enqueue_job.assert_not_called()

    def test_changed_email_resets_verification_and_sends_a_new_mail(
        self, client, make_user, fake_arq_pool, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FRONTEND_VERIFY_EMAIL_URL", "https://example.test/verify")
        headers, _old_email = _auth_headers(client, make_user)
        new_email = f"{_unique('new').lower()}@example.com"

        response = client.put(
            "/profile", json=_payload(email=new_email), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == new_email
        assert body["email_verified_at"] is None
        fake_arq_pool.enqueue_job.assert_called_once()
        args = fake_arq_pool.enqueue_job.call_args.args
        assert args[0] == "send_verification_email_task"
        assert args[1] == new_email

    def test_password_change_allows_login_with_the_new_password(
        self, client, make_user
    ):
        headers, email = _auth_headers(client, make_user, password="Passwort123")

        response = client.put(
            "/profile",
            json=_payload(
                email=email,
                change_password=True,
                password="NeuesPassw0rt",
                password_confirmation="NeuesPassw0rt",
            ),
            headers=headers,
        )
        assert response.status_code == 200

        login_response = client.post(
            "/auth/login", data={"username": email, "password": "NeuesPassw0rt"}
        )
        assert login_response.status_code == 200

    def test_duplicate_name_combo_returns_422_on_both_fields(
        self, client, make_user, db_session
    ):
        surname, givenname = _unique("Doppel"), "Gustav"
        other = make_user()
        other.surname = surname.upper()
        other.givenname = givenname
        db_session.commit()

        headers, email = _auth_headers(client, make_user)
        response = client.put(
            "/profile",
            json=_payload(email=email, surname=surname, givenname=givenname),
            headers=headers,
        )
        assert response.status_code == 422
        fields = {error["loc"][1] for error in response.json()["detail"]}
        assert fields == {"surname", "givenname"}
