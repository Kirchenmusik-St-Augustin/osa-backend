import uuid


def _unique(base: str = "Fee") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None
) -> dict[str, str]:
    user = make_user(
        password="correct-password", roles=roles if roles is not None else ["disponent"]
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_list_requires_authentication(self, client):
        response = client.get("/fees")
        assert response.status_code == 401

    def test_list_rejects_non_disponent(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/fees", headers=headers)
        assert response.status_code == 403

    def test_create_rejects_non_disponent(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.post(
            "/fees", json={"name": _unique(), "amount": 80}, headers=headers
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_list_update_delete_fee(self, client, make_user):
        headers = _auth_headers(client, make_user)
        name = _unique("Instrumentalist")

        create_response = client.post(
            "/fees", json={"name": name, "amount": 80}, headers=headers
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == name
        assert created["amount"] == 80

        list_response = client.get("/fees", headers=headers)
        assert name in [item["name"] for item in list_response.json()]

        new_name = _unique("Konzertmeister")
        update_response = client.put(
            f"/fees/{created['id']}",
            json={"name": new_name, "amount": 100},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["amount"] == 100

        delete_response = client.delete(f"/fees/{created['id']}", headers=headers)
        assert delete_response.status_code == 200

        final_list = client.get("/fees", headers=headers)
        assert new_name not in [item["name"] for item in final_list.json()]

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put(
            "/fees/999999", json={"name": _unique(), "amount": 10}, headers=headers
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/fees/999999", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_duplicate_name_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        name = _unique()
        client.post("/fees", json={"name": name, "amount": 10}, headers=headers)
        response = client.post(
            "/fees", json={"name": name, "amount": 20}, headers=headers
        )
        assert response.status_code == 422

    def test_extra_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/fees",
            json={"name": _unique(), "amount": 10, "order": 5},
            headers=headers,
        )
        assert response.status_code == 422
