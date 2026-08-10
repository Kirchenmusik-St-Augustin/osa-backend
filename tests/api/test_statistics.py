def _auth_headers(client, make_user) -> dict[str, str]:
    user = make_user(password="correct-password")
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_requires_authentication(self, client):
        response = client.get("/statistics")
        assert response.status_code == 401

    def test_any_authenticated_user_may_call_it(self, client, make_user):
        # 1:1 Legacy: no Policy/Gate exists for Statistics at all.
        headers = _auth_headers(client, make_user)
        response = client.get("/statistics", headers=headers)
        assert response.status_code == 200


class TestGetStatistics:
    def test_returns_the_expected_shape(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/statistics", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "users",
            "performances",
            "ordinariumworks",
            "propriumworks",
            "email",
        }
        assert set(body["email"].keys()) == {
            "active",
            "period_days",
            "threshold",
            "sent",
        }

    def test_counts_are_non_negative_integers(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/statistics", headers=headers)

        body = response.json()
        for key in ("users", "performances", "ordinariumworks", "propriumworks"):
            assert isinstance(body[key], int)
            assert body[key] >= 0
