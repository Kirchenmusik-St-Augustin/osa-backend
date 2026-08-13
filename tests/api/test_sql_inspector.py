def _auth_headers(client, make_user, *, administrator: bool = False) -> dict[str, str]:
    user = make_user(password="correct-password", administrator=administrator)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_list_tables_requires_authentication(self, client):
        response = client.get("/administrator/sql-inspector/tables")
        assert response.status_code == 401

    def test_list_tables_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/administrator/sql-inspector/tables", headers=headers)
        assert response.status_code == 403

    def test_list_tables_allows_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get("/administrator/sql-inspector/tables", headers=headers)
        assert response.status_code == 200

    def test_table_data_requires_authentication(self, client):
        response = client.get("/administrator/sql-inspector/tables/users")
        assert response.status_code == 401

    def test_table_data_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get(
            "/administrator/sql-inspector/tables/users", headers=headers
        )
        assert response.status_code == 403


class TestListTables:
    def test_returns_known_table_names(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get("/administrator/sql-inspector/tables", headers=headers)

        assert response.status_code == 200
        assert "users" in response.json()


class TestTableData:
    def test_unknown_table_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/not_a_real_table", headers=headers
        )

        assert response.status_code == 404

    def test_known_table_returns_expected_shape(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users", headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["table_name"] == "users"
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert any(
            col["name"] == "id" and col["primary_key"] for col in body["columns"]
        )

    def test_pagination_query_params_are_respected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page": 2, "page_size": 5},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 2
        assert body["page_size"] == 5

    def test_page_below_one_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page": 0},
            headers=headers,
        )

        assert response.status_code == 422

    def test_page_size_above_upper_bound_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page_size": 101},
            headers=headers,
        )

        assert response.status_code == 422
