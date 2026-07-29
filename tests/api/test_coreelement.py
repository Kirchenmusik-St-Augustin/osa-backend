import uuid


def _unique(base: str = "Element") -> str:
    """Every test gets its own collision-free name -- tests/conftest.py's
    shared SQLite file has no per-test rollback (1:1 make_user's uuid-based
    emails for the same reason), and coreelement names are globally unique
    per type, unlike Users."""
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, administrator: bool = True, roles: list[str] | None = None
) -> dict[str, str]:
    user = make_user(
        password="correct-password", administrator=administrator, roles=roles
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_list_requires_authentication(self, client):
        response = client.get("/coreelements/instrument")
        assert response.status_code == 401

    def test_list_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=False)
        response = client.get("/coreelements/instrument", headers=headers)
        assert response.status_code == 403

    def test_create_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=False)
        response = client.post(
            "/coreelements/instrument", json={"name": _unique()}, headers=headers
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_list_update_delete_instrument(self, client, make_user):
        headers = _auth_headers(client, make_user)
        name = _unique("Fagott")

        create_response = client.post(
            "/coreelements/instrument", json={"name": name}, headers=headers
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == name

        list_response = client.get("/coreelements/instrument", headers=headers)
        assert name in [item["name"] for item in list_response.json()]

        new_name = _unique("Kontrafagott")
        update_response = client.put(
            f"/coreelements/instrument/{created['id']}",
            json={"name": new_name},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == new_name

        delete_response = client.delete(
            f"/coreelements/instrument/{created['id']}", headers=headers
        )
        assert delete_response.status_code == 200

        final_list = client.get("/coreelements/instrument", headers=headers)
        assert new_name not in [item["name"] for item in final_list.json()]

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put(
            "/coreelements/instrument/999", json={"name": _unique()}, headers=headers
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/coreelements/instrument/999", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_name_too_short_returns_422_with_field_error(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/coreelements/instrument", json={"name": "ab"}, headers=headers
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail[0]["loc"] == ["body", "name"]

    def test_duplicate_name_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        name = _unique("Fagott")
        client.post("/coreelements/instrument", json={"name": name}, headers=headers)
        response = client.post(
            "/coreelements/instrument", json={"name": name}, headers=headers
        )
        assert response.status_code == 422
        assert "bereits vergeben" in response.json()["detail"][0]["msg"]

    def test_location_without_address_and_color_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/coreelements/location", json={"name": _unique()}, headers=headers
        )
        assert response.status_code == 422
        fields = {error["loc"][-1] for error in response.json()["detail"]}
        assert fields == {"address", "color"}

    def test_location_with_all_fields_succeeds(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/coreelements/location",
            json={
                "name": _unique("Chorraum"),
                "address": "Hauptstraße 1",
                "color": "ff0000",
            },
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["address"] == "Hauptstraße 1"

    def test_extra_body_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/coreelements/instrument",
            json={"name": _unique(), "unknown_field": "x"},
            headers=headers,
        )
        assert response.status_code == 422


class TestDeleteInUse:
    def test_role_delete_blocked_while_users_assigned(self, client, make_user):
        headers = _auth_headers(client, make_user)
        role_name = _unique("r")[:16]
        create_response = client.post(
            "/coreelements/role",
            json={
                "name": role_name,
                "label": _unique("Noten"),
                "description": "Notenverwaltung",
            },
            headers=headers,
        )
        role_id = create_response.json()["id"]
        make_user(roles=[role_name])

        delete_response = client.delete(
            f"/coreelements/role/{role_id}", headers=headers
        )

        assert delete_response.status_code == 422
        assert "noch in Verwendung" in delete_response.json()["detail"][0]["msg"]


class TestDeleteInUseViaOrdinariumworkPosition:
    """Retrofit regression guard: Instrument/Voice delete is now blocked
    once Schritt 4 (Repertoire) wires them into an Ordinariumwork's setup
    positions -- see _make_ordinariumwork_position_dependency_check in
    coreelement_service.py."""

    def test_instrument_delete_blocked_while_referenced_by_ordinariumwork(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user)
        instrument_response = client.post(
            "/coreelements/instrument",
            json={"name": _unique("Fagott")},
            headers=headers,
        )
        instrument_id = instrument_response.json()["id"]

        # artistMaintain/ordinariumworkMaintain require role planner/
        # disponent, not the administrator flag used above for
        # coreelements -- use a dedicated planner user for these calls.
        planner_headers = _auth_headers(client, make_user, roles=["planner"])
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
            headers=planner_headers,
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
                "setup": {
                    "instruments": [{"id": instrument_id, "quantity": 1}],
                    "voices": [],
                },
            },
            headers=planner_headers,
        )

        delete_response = client.delete(
            f"/coreelements/instrument/{instrument_id}", headers=headers
        )

        assert delete_response.status_code == 422
        assert "noch in Verwendung" in delete_response.json()["detail"][0]["msg"]


class TestMove:
    def test_move_up_swaps_order_with_previous_item(self, client, make_user):
        headers = _auth_headers(client, make_user)
        first_name, second_name = _unique("Introitus"), _unique("Graduale")
        client.post(
            "/coreelements/propriumelement", json={"name": first_name}, headers=headers
        )
        second = client.post(
            "/coreelements/propriumelement", json={"name": second_name}, headers=headers
        )
        second_id = second.json()["id"]

        response = client.post(
            f"/coreelements/propriumelement/{second_id}/move/up", headers=headers
        )

        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names.index(second_name) + 1 == names.index(first_name)

    def test_move_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post("/coreelements/instrument/999/move/up", headers=headers)
        assert response.status_code == 404

    def test_move_invalid_direction_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        create_response = client.post(
            "/coreelements/instrument", json={"name": _unique()}, headers=headers
        )
        item_id = create_response.json()["id"]

        response = client.post(
            f"/coreelements/instrument/{item_id}/move/sideways", headers=headers
        )

        assert response.status_code == 422


class TestQueryCount:
    def test_list_query_count_does_not_scale_with_row_count(
        self, client, make_user, count_queries
    ):
        """Regression guard for N+1 in list_coreelements(): a plain
        `SELECT ... ORDER BY` must issue the same number of statements
        regardless of how many rows come back (CLAUDE.md testing_constraints)."""
        headers = _auth_headers(client, make_user)

        client.post(
            "/coreelements/instrument", json={"name": _unique()}, headers=headers
        )
        with count_queries() as small:
            small_response = client.get("/coreelements/instrument", headers=headers)

        for _ in range(5):
            client.post(
                "/coreelements/instrument", json={"name": _unique()}, headers=headers
            )
        with count_queries() as large:
            large_response = client.get("/coreelements/instrument", headers=headers)

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()) > len(small_response.json())
        assert large.count == small.count
