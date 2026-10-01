import uuid
from datetime import UTC, datetime


def _unique(base: str = "AdminUser") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None, administrator: bool = False
) -> dict[str, str]:
    user = make_user(
        password="correct-password",
        roles=roles if roles is not None else [],
        administrator=administrator,
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_search_requires_authentication(self, client):
        response = client.get("/administrator/users/search", params={"q": "a"})
        assert response.status_code == 401

    def test_search_rejects_disponent_without_administrator_flag(
        self, client, make_user
    ):
        # userAdministrate is strictly administrator-only -- unlike
        # userMaintain, the disponent role alone is NOT enough.
        headers = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get(
            "/administrator/users/search", params={"q": "a"}, headers=headers
        )
        assert response.status_code == 403

    def test_search_allows_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get(
            "/administrator/users/search", params={"q": "a"}, headers=headers
        )
        assert response.status_code == 200


class TestSearchAndDeletedList:
    def test_search_finds_soft_deleted_users(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user, administrator=True)
        marker = _unique("Geloescht")
        deleted_user = make_user()
        deleted_user.surname = marker
        deleted_user.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.get(
            "/administrator/users/search", params={"q": marker}, headers=headers
        )
        assert response.status_code == 200
        assert str(deleted_user.id) in [item["id"] for item in response.json()]

    def test_deleted_list_only_shows_soft_deleted_users(
        self, client, make_user, db_session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        active = make_user()
        deleted_user = make_user()
        deleted_user.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.get("/administrator/users/deleted", headers=headers)
        ids = [item["id"] for item in response.json()]
        assert str(deleted_user.id) in ids
        assert active.id not in ids


class TestShow:
    def test_shows_a_soft_deleted_user_too(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user, administrator=True)
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.get(f"/administrator/users/{user.id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["user"]["deleted_at"] is not None

    def test_includes_contact_data_and_last_activity(
        self, client, make_user, db_session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        user = make_user(email="contact@example.test")
        user.phone = "+43 660 1234567"
        user.auth_lastsignal = datetime.now(UTC)
        db_session.commit()

        response = client.get(f"/administrator/users/{user.id}", headers=headers)
        payload = response.json()["user"]
        assert payload["email"] == "contact@example.test"
        assert payload["phone"] == "+43 660 1234567"
        assert payload["auth_lastsignal"] is not None

    def test_phone_is_null_when_not_set(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        user = make_user()

        response = client.get(f"/administrator/users/{user.id}", headers=headers)
        assert response.json()["user"]["phone"] is None

    def test_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get(f"/administrator/users/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404


class TestRestore:
    def test_restores_a_deleted_user(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user, administrator=True)
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.post(
            f"/administrator/users/{user.id}/restore", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["user"]["deleted_at"] is None


class TestUnlock:
    def test_unlocks_a_locked_user(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        user = make_user(auth_locked=True)

        response = client.post(
            f"/administrator/users/{user.id}/unlock", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["user"]["auth_locked"] is False


class TestSetPassword:
    def test_returns_a_one_time_password(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()

        response = client.post(
            f"/administrator/users/{target.id}/set-password", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["newpw"]) == 10

    def test_get_response_never_includes_newpw(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        client.post(f"/administrator/users/{target.id}/set-password", headers=headers)

        show_response = client.get(f"/administrator/users/{target.id}", headers=headers)
        assert (
            "newpw" not in show_response.json() or show_response.json()["newpw"] is None
        )

    def test_self_targeting_is_forbidden(self, client, make_user):
        admin = make_user(password="correct-password", administrator=True)
        login = client.post(
            "/auth/login",
            data={"username": admin.email, "password": "correct-password"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            f"/administrator/users/{admin.id}/set-password", headers=headers
        )
        assert response.status_code == 403


class TestPurge:
    def test_non_administrator_is_forbidden(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=["disponent"])
        target = make_user()

        response = client.delete(f"/administrator/users/{target.id}", headers=headers)
        assert response.status_code == 403

    def test_purges_a_deleted_user_without_history(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        target.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.delete(f"/administrator/users/{target.id}", headers=headers)
        assert response.status_code == 200
        follow_up = client.get(f"/administrator/users/{target.id}", headers=headers)
        assert follow_up.status_code == 404

    def test_active_user_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()

        response = client.delete(f"/administrator/users/{target.id}", headers=headers)
        assert response.status_code == 422

    def test_user_with_history_is_rejected(
        self, client, make_user, db_session, add_user_history
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        add_user_history(target, "booking")
        target.deleted_at = datetime.now(UTC)
        db_session.commit()

        response = client.delete(f"/administrator/users/{target.id}", headers=headers)
        assert response.status_code == 422
        still_there = client.get(f"/administrator/users/{target.id}", headers=headers)
        assert still_there.status_code == 200

    def test_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.delete(
            f"/administrator/users/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == 404

    def test_detail_reports_purgeable_flag(
        self, client, make_user, db_session, add_user_history
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        clean = make_user()
        clean.deleted_at = datetime.now(UTC)
        with_history = make_user()
        add_user_history(with_history, "request")
        with_history.deleted_at = datetime.now(UTC)
        active = make_user()
        db_session.commit()

        def purgeable(user) -> bool:
            response = client.get(f"/administrator/users/{user.id}", headers=headers)
            return response.json()["user"]["purgeable"]

        assert purgeable(clean) is True
        assert purgeable(with_history) is False
        assert purgeable(active) is False
