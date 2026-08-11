import uuid

from app.services import score_service


def _unique(base: str = "Werk") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _payload(**overrides: object) -> dict[str, object]:
    return {
        **score_service.get_defaults(),
        "kasten": "A",
        "boxnr": "1",
        "inhalt": "Partitur",
        "werk": _unique(),
        **overrides,
    }


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None
) -> dict[str, str]:
    user = make_user(
        password="correct-password", roles=roles if roles is not None else ["scores"]
    )
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_fields_config_requires_authentication(self, client):
        response = client.get("/scores/fields-config")
        assert response.status_code == 401

    def test_fields_config_rejects_non_scores_role(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/scores/fields-config", headers=headers)
        assert response.status_code == 403

    def test_create_rejects_non_scores_role(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.post("/scores", json=_payload(), headers=headers)
        assert response.status_code == 403


class TestFieldsConfigAndDefaults:
    def test_fields_config_returns_all_94_fields(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/scores/fields-config", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 94

    def test_defaults_returns_zeroed_and_blank_form(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/scores/defaults", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["kasten"] == ""
        assert body["violine1"] == 0


class TestCrudRoundtrip:
    def test_create_search_show_update(self, client, make_user):
        headers = _auth_headers(client, make_user)
        werk = _unique("Konzertwerk")

        create_response = client.post(
            "/scores", json=_payload(werk=werk, surname="Haydn"), headers=headers
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["fields"]["werk"] == werk
        assert created["fields"]["surname"] == "HAYDN"
        assert created["created_at"] is not None

        search_response = client.get(
            "/scores/search", params={"q": werk}, headers=headers
        )
        assert search_response.status_code == 200
        assert any(item["id"] == created["id"] for item in search_response.json())

        show_response = client.get(f"/scores/{created['id']}", headers=headers)
        assert show_response.status_code == 200
        assert show_response.json()["fields"]["werk"] == werk

        update_response = client.put(
            f"/scores/{created['id']}",
            json=_payload(werk=werk, bemerkung="Aktualisiert"),
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["fields"]["bemerkung"] == "Aktualisiert"

    def test_show_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/scores/999999", headers=headers)
        assert response.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put("/scores/999999", json=_payload(), headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_duplicate_werk_within_same_scope_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        werk = _unique()
        client.post(
            "/scores", json=_payload(werk=werk, surname="Bach"), headers=headers
        )
        response = client.post(
            "/scores", json=_payload(werk=werk, surname="Bach"), headers=headers
        )
        assert response.status_code == 422

    def test_invalid_select_value_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/scores", json=_payload(inhalt="NichtErlaubterWert"), headers=headers
        )
        assert response.status_code == 422

    def test_blank_inhalt_is_rejected_despite_being_a_listed_value(
        self, client, make_user
    ):
        # Regression test: Legacy's own `values` list for the required
        # "inhalt" select still carries a leading "" placeholder, but
        # `required` makes it practically unreachable -- must 422, not 201.
        headers = _auth_headers(client, make_user)
        response = client.post("/scores", json=_payload(inhalt=""), headers=headers)
        assert response.status_code == 422

    def test_number_field_out_of_range_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/scores", json=_payload(violine1=10000), headers=headers
        )
        assert response.status_code == 422

    def test_missing_field_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        payload = _payload()
        del payload["bemerkung"]
        response = client.post("/scores", json=payload, headers=headers)
        assert response.status_code == 422

    def test_extra_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/scores", json={**_payload(), "unknown_field": "x"}, headers=headers
        )
        assert response.status_code == 422


class TestNoDeleteRoute:
    def test_delete_is_not_allowed(self, client, make_user):
        headers = _auth_headers(client, make_user)
        create_response = client.post("/scores", json=_payload(), headers=headers)
        score_id = create_response.json()["id"]

        response = client.delete(f"/scores/{score_id}", headers=headers)

        assert response.status_code == 405
