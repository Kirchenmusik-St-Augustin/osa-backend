import uuid


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None
) -> dict[str, str]:
    user = make_user(
        password="correct-password", roles=roles if roles is not None else ["planner"]
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_artist(client, headers) -> int:
    response = client.post(
        "/artists",
        json={
            "surname": _unique("Composer"),
            "givenname": _unique("First"),
            "description": None,
            "birthyear": None,
            "deathyear": None,
            "composer": True,
            "conductor": False,
        },
        headers=headers,
    )
    return response.json()["id"]


def _make_instrument(client, make_user) -> int:
    # instrumentMaintain requires the administrator flag, unlike
    # ordinariumworkMaintain (planner/disponent role) -- a separate admin
    # user creates the instrument fixture.
    admin_user = make_user(password="correct-password", administrator=True)
    login_response = client.post(
        "/auth/login",
        data={"username": admin_user.email, "password": "correct-password"},
    )
    admin_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
    response = client.post(
        "/coreelements/instrument",
        json={"name": _unique("Instrument")},
        headers=admin_headers,
    )
    return response.json()["id"]


class TestPermissionGuard:
    def test_search_requires_authentication(self, client):
        response = client.get("/ordinariumworks/search", params={"q": "x"})
        assert response.status_code == 401

    def test_search_rejects_user_without_planner_or_disponent_role(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get(
            "/ordinariumworks/search", params={"q": "x"}, headers=headers
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_get_update_delete_ordinariumwork(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=["planner", "disponent"])
        artist_id = _make_artist(client, headers)
        name = _unique("Krönungsmesse")

        create_response = client.post(
            "/ordinariumworks",
            json={
                "name": name,
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [], "voices": []},
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == name

        get_response = client.get(f"/ordinariumworks/{created['id']}", headers=headers)
        assert get_response.status_code == 200

        new_name = _unique("Requiem")
        update_response = client.put(
            f"/ordinariumworks/{created['id']}",
            json={
                "name": new_name,
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [], "voices": []},
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == new_name

        delete_response = client.delete(
            f"/ordinariumworks/{created['id']}", headers=headers
        )
        assert delete_response.status_code == 200

        final_get = client.get(f"/ordinariumworks/{created['id']}", headers=headers)
        assert final_get.status_code == 404

    def test_get_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/ordinariumworks/999", headers=headers)
        assert response.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)
        response = client.put(
            "/ordinariumworks/999",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [], "voices": []},
            },
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/ordinariumworks/999", headers=headers)
        assert response.status_code == 404


class TestSetup:
    def test_create_with_setup_and_read_it_back(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)
        instrument_id = _make_instrument(client, make_user)

        create_response = client.post(
            "/ordinariumworks",
            json={
                "name": _unique("Messe"),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {
                    "instruments": [{"id": instrument_id, "quantity": 2}],
                    "voices": [],
                },
            },
            headers=headers,
        )
        work_id = create_response.json()["id"]

        setup_response = client.get(
            f"/ordinariumworks/{work_id}/setup", headers=headers
        )

        assert setup_response.status_code == 200
        instruments = setup_response.json()["instruments"]
        assert [(item["id"], item["quantity"]) for item in instruments] == [
            (instrument_id, 2)
        ]
        assert setup_response.json()["voices"] == []

    def test_setup_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/ordinariumworks/999/setup", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_unknown_instrument_in_setup_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)

        response = client.post(
            "/ordinariumworks",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [{"id": 999999, "quantity": 1}], "voices": []},
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_extra_body_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)

        response = client.post(
            "/ordinariumworks",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [], "voices": []},
                "unknown_field": "x",
            },
            headers=headers,
        )

        assert response.status_code == 422
