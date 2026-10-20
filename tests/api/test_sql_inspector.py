from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.sent_email import SentEmail


def _auth_headers_for(
    client, user, password: str = "correct-password"
) -> dict[str, str]:
    response = client.post(
        "/auth/login", data={"username": user.email, "password": password}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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

    def test_page_above_the_upper_bound_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page": 100_001},
            headers=headers,
        )

        assert response.status_code == 422

    def test_the_last_allowed_page_answers_with_no_rows(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page": 100_000},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["rows"] == []

    def test_page_size_above_upper_bound_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        response = client.get(
            "/administrator/sql-inspector/tables/users",
            params={"page_size": 101},
            headers=headers,
        )

        assert response.status_code == 422


class TestCredentialMasking:
    """The table browser lists every column but never shows the values of
    credentials and credential equivalents."""

    _MASKED = "__masked__"

    def _rows(self, client, headers, table_name: str) -> dict:
        response = client.get(
            f"/administrator/sql-inspector/tables/{table_name}",
            params={"page_size": 100},
            headers=headers,
        )
        assert response.status_code == 200
        return response.json()

    def test_credential_columns_are_masked_but_still_listed(
        self, client, make_user, db_session
    ):
        admin = make_user(
            password="correct-password", administrator=True, email="mask@example.test"
        )
        admin.auth_remember_token = "remember-secret"
        db_session.add(
            PasswordResetToken(email="mask@example.test", token="reset-hash-secret")
        )
        db_session.add(SentEmail(subject="Mask probe", body="https://x.test/?t=secret"))
        db_session.commit()
        headers = _auth_headers_for(client, admin)

        masked_columns = {
            "users": ["auth_password", "auth_remember_token"],
            "personal_access_tokens": ["token", "abilities"],
            "password_reset_tokens": ["token"],
            "sent_emails": ["body"],
        }
        for table_name, columns in masked_columns.items():
            data = self._rows(client, headers, table_name)
            listed = {column["name"] for column in data["columns"]}
            for column in columns:
                values = {
                    row[column] for row in data["rows"] if row[column] is not None
                }
                assert column in listed
                assert values == {self._MASKED}, f"{table_name}.{column}"

    def test_other_columns_keep_their_values(self, client, make_user):
        admin = make_user(
            password="correct-password", administrator=True, email="plain@example.test"
        )
        headers = _auth_headers_for(client, admin)

        data = self._rows(client, headers, "users")

        assert "plain@example.test" in {row["email"] for row in data["rows"]}

    def test_empty_credential_values_stay_empty(self, client, make_user):
        admin = make_user(password="correct-password", administrator=True)
        headers = _auth_headers_for(client, admin)

        data = self._rows(client, headers, "users")

        remember_tokens = {row["auth_remember_token"] for row in data["rows"]}
        assert remember_tokens == {None}
