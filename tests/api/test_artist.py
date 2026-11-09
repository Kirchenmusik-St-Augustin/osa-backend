import uuid
from typing import ClassVar

import pytest

from tests.login import login_headers


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None
) -> dict[str, str]:
    return login_headers(
        client, make_user, roles=roles if roles is not None else ["planner"]
    )


_MISSING_ID = "00000000-0000-7000-8000-000000000000"
_ARTIST_ROUTES = [
    ("GET", "/artists/search?q=x"),
    ("POST", "/artists"),
    ("GET", "/artists/composers"),
    ("GET", f"/artists/{_MISSING_ID}"),
    ("PUT", f"/artists/{_MISSING_ID}"),
    ("DELETE", f"/artists/{_MISSING_ID}"),
]


class TestPermissionGuard:
    def test_search_requires_authentication(self, client):
        response = client.get("/artists/search", params={"q": "x"})
        assert response.status_code == 401

    def test_search_rejects_user_without_planner_or_disponent_role(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/artists/search", params={"q": "x"}, headers=headers)
        assert response.status_code == 403

    @pytest.mark.parametrize(("method", "path"), _ARTIST_ROUTES)
    def test_every_route_requires_authentication(self, client, method, path):
        response = client.request(method, path, json={})
        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path"), _ARTIST_ROUTES)
    def test_every_route_rejects_a_user_without_the_permission(
        self, client, make_user, method, path
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.request(method, path, json={}, headers=headers)
        assert response.status_code == 403

    def test_search_allows_disponent_role(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get("/artists/search", params={"q": "x"}, headers=headers)
        assert response.status_code == 200


class TestCrudRoundtrip:
    def test_create_get_update_delete_artist(self, client, make_user):
        headers = _auth_headers(client, make_user)
        surname, givenname = _unique("Muster"), _unique("Max")

        create_response = client.post(
            "/artists",
            json={
                "surname": surname,
                "givenname": givenname,
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": True,
                "conductor": False,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["surname"] == surname.upper()

        get_response = client.get(f"/artists/{created['id']}", headers=headers)
        assert get_response.status_code == 200

        new_description = _unique("Beschreibung")
        update_response = client.put(
            f"/artists/{created['id']}",
            json={
                "surname": surname,
                "givenname": givenname,
                "description": new_description,
                "birthyear": None,
                "deathyear": None,
                "composer": True,
                "conductor": False,
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["description"] == new_description

        delete_response = client.delete(f"/artists/{created['id']}", headers=headers)
        assert delete_response.status_code == 200

        final_get = client.get(f"/artists/{created['id']}", headers=headers)
        assert final_get.status_code == 404

    def test_get_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get(f"/artists/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put(
            f"/artists/{uuid.uuid4()}",
            json={
                "surname": _unique(),
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": False,
                "conductor": False,
            },
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete(f"/artists/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_blank_surname_returns_422_with_field_error(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/artists",
            json={
                "surname": "   ",
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": False,
                "conductor": False,
            },
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "surname"]

    def test_a_short_surname_is_accepted_and_stored_without_padding(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/artists",
            json={
                "surname": "  li ",
                "givenname": f" {_unique()} ",
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": False,
                "conductor": False,
            },
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["surname"] == "LI"
        assert response.json()["givenname"] == response.json()["givenname"].strip()

    def test_extra_body_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/artists",
            json={
                "surname": _unique(),
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": False,
                "conductor": False,
                "unknown_field": "x",
            },
            headers=headers,
        )
        assert response.status_code == 422


class TestListComposers:
    def test_requires_authentication(self, client):
        response = client.get("/artists/composers")
        assert response.status_code == 401

    def test_only_returns_composer_flagged_artists(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_name = _unique("Komponist")
        client.post(
            "/artists",
            json={
                "surname": composer_name,
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": True,
                "conductor": False,
            },
            headers=headers,
        )
        conductor_only_name = _unique("Dirigent")
        client.post(
            "/artists",
            json={
                "surname": conductor_only_name,
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": False,
                "conductor": True,
            },
            headers=headers,
        )

        response = client.get("/artists/composers", headers=headers)

        assert response.status_code == 200
        surnames = [item["label"].split(",")[0] for item in response.json()["items"]]
        assert composer_name.upper() in surnames
        assert conductor_only_name.upper() not in surnames


class TestDeleteInUse:
    def test_delete_blocked_while_ordinariumwork_references_artist(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user)
        artist_response = client.post(
            "/artists",
            json={
                "surname": _unique(),
                "givenname": _unique(),
                "description": None,
                "birthyear": None,
                "deathyear": None,
                "composer": True,
                "conductor": False,
            },
            headers=headers,
        )
        artist_id = artist_response.json()["id"]
        client.post(
            "/ordinariumworks",
            json={
                "name": _unique("Werk"),
                "description": None,
                "artist_id": artist_id,
                "duration": None,
                "demanding": False,
                "setup": {"instruments": [], "voices": []},
            },
            headers=headers,
        )

        delete_response = client.delete(f"/artists/{artist_id}", headers=headers)

        assert delete_response.status_code == 422
        assert "noch in Verwendung" in delete_response.json()["detail"][0]["msg"]


class TestWritePermissionsAndErrors:
    _BODY: ClassVar[dict[str, object]] = {
        "surname": "Haydn",
        "givenname": "Joseph",
        "description": None,
        "birthyear": None,
        "deathyear": None,
        "composer": True,
        "conductor": False,
    }

    def test_create_update_and_delete_require_planner_or_disponent(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        some_id = uuid.uuid4()

        responses = [
            client.post("/artists", json=self._BODY, headers=headers),
            client.put(f"/artists/{some_id}", json=self._BODY, headers=headers),
            client.delete(f"/artists/{some_id}", headers=headers),
        ]

        assert [response.status_code for response in responses] == [403, 403, 403]

    def test_write_routes_require_authentication(self, client):
        some_id = uuid.uuid4()

        responses = [
            client.post("/artists", json=self._BODY),
            client.put(f"/artists/{some_id}", json=self._BODY),
            client.delete(f"/artists/{some_id}"),
        ]

        assert [response.status_code for response in responses] == [401, 401, 401]

    def test_unknown_artist_is_404_for_get_update_and_delete(self, client, make_user):
        headers = _auth_headers(client, make_user)
        unknown = uuid.uuid4()

        responses = [
            client.get(f"/artists/{unknown}", headers=headers),
            client.put(f"/artists/{unknown}", json=self._BODY, headers=headers),
            client.delete(f"/artists/{unknown}", headers=headers),
        ]

        assert [response.status_code for response in responses] == [404, 404, 404]

    def test_the_same_name_in_another_letter_case_is_rejected_at_both_fields(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user)
        surname, givenname = _unique("Dupe"), _unique("Case")
        body = {**self._BODY, "surname": surname, "givenname": givenname}
        assert client.post("/artists", json=body, headers=headers).status_code == 201

        response = client.post(
            "/artists",
            json={**body, "surname": surname.upper(), "givenname": givenname.lower()},
            headers=headers,
        )

        assert response.status_code == 422
        fields = {error["loc"][-1] for error in response.json()["detail"]}
        assert fields == {"surname", "givenname"}
