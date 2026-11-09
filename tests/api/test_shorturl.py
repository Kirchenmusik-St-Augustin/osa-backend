import uuid

import pytest

from tests.login import login_headers


def _unique(base: str = "path") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None
) -> dict[str, str]:
    return login_headers(
        client, make_user, roles=roles if roles is not None else ["shorturls"]
    )


class TestPermissionGuard:
    def test_list_requires_authentication(self, client):
        response = client.get("/shorturls")
        assert response.status_code == 401

    def test_list_rejects_non_shorturls_role(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/shorturls", headers=headers)
        assert response.status_code == 403

    def test_create_rejects_non_shorturls_role(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.post(
            "/shorturls",
            json={"path": _unique(), "target": "example.org"},
            headers=headers,
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_list_update_delete_shorturl(self, client, make_user):
        headers = _auth_headers(client, make_user)
        path = _unique("konzert")

        create_response = client.post(
            "/shorturls",
            json={"path": path, "target": "example.org/foo"},
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["path"] == path
        assert created["target"] == "https://example.org/foo"
        assert created["counter"] == 0

        list_response = client.get("/shorturls", headers=headers)
        assert list_response.status_code == 200
        body = list_response.json()
        assert body["urlprefix"].startswith("https://")
        assert path in [item["path"] for item in body["items"]]

        new_path = _unique("orgel")
        update_response = client.put(
            f"/shorturls/{created['id']}",
            json={"path": new_path, "target": "example.org/bar"},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["target"] == "https://example.org/bar"

        delete_response = client.delete(f"/shorturls/{created['id']}", headers=headers)
        assert delete_response.status_code == 200

        final_list = client.get("/shorturls", headers=headers)
        assert new_path not in [item["path"] for item in final_list.json()["items"]]

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put(
            f"/shorturls/{uuid.uuid4()}",
            json={"path": _unique(), "target": "example.org"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete(f"/shorturls/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404


class TestValidation:
    def test_duplicate_path_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        path = _unique()
        client.post(
            "/shorturls",
            json={"path": path, "target": "example.org"},
            headers=headers,
        )
        response = client.post(
            "/shorturls",
            json={"path": path, "target": "example.org/other"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_invalid_path_characters_return_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/shorturls",
            json={"path": "bad path!", "target": "example.org"},
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("path", ["/abc", "abc/", "a//b"])
    def test_misplaced_slashes_return_a_german_error_at_the_path(
        self, client, make_user, path
    ):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/shorturls",
            json={"path": path, "target": "example.org"},
            headers=headers,
        )
        assert response.status_code == 422
        error = response.json()["detail"][0]
        assert error["loc"][-1] == "path"
        assert error["msg"].startswith("Erlaubt sind Buchstaben")

    @pytest.mark.parametrize(
        "target", ["javascript:alert(1)", "ftp://example.org", "file:///etc/passwd"]
    )
    def test_a_target_that_is_not_http_returns_a_field_error_at_target(
        self, client, make_user, target
    ):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/shorturls",
            json={"path": _unique(), "target": target},
            headers=headers,
        )
        assert response.status_code == 422
        assert "http- und https" in str(response.json())

    def test_extra_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/shorturls",
            json={"path": _unique(), "target": "example.org", "counter": 5},
            headers=headers,
        )
        assert response.status_code == 422
