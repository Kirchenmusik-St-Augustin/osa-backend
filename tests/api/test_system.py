def _auth_headers(client, make_user) -> dict[str, str]:
    user = make_user(password="correct-password")
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_requires_authentication(self, client):
        response = client.get("/system/environment")
        assert response.status_code == 401

    def test_any_authenticated_user_may_call_it(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/system/environment", headers=headers)
        assert response.status_code == 200


class TestGetEnvironment:
    def test_returns_the_configured_environment(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/system/environment", headers=headers)

        assert response.status_code == 200
        assert response.json() == {"environment": "test"}
