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


class TestPermissionGuard:
    def test_search_requires_authentication(self, client):
        response = client.get("/propriumworks/search", params={"q": "x"})
        assert response.status_code == 401

    def test_search_rejects_user_without_planner_or_disponent_role(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get(
            "/propriumworks/search", params={"q": "x"}, headers=headers
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_get_update_delete_propriumwork(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)
        name = _unique("Graduale")

        create_response = client.post(
            "/propriumworks",
            json={
                "name": name,
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == name

        get_response = client.get(f"/propriumworks/{created['id']}", headers=headers)
        assert get_response.status_code == 200

        new_name = _unique("Offertorium")
        update_response = client.put(
            f"/propriumworks/{created['id']}",
            json={
                "name": new_name,
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == new_name

        delete_response = client.delete(
            f"/propriumworks/{created['id']}", headers=headers
        )
        assert delete_response.status_code == 200

        final_get = client.get(f"/propriumworks/{created['id']}", headers=headers)
        assert final_get.status_code == 404

    def test_get_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/propriumworks/999", headers=headers)
        assert response.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)
        response = client.put(
            "/propriumworks/999",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
            },
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/propriumworks/999", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_unknown_artist_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/propriumworks",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": 999999,
                "duration": None,
                "demanding": False,
            },
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "artist_id"]

    def test_extra_body_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        artist_id = _make_artist(client, headers)
        response = client.post(
            "/propriumworks",
            json={
                "name": _unique(),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "unknown_field": "x",
            },
            headers=headers,
        )
        assert response.status_code == 422
