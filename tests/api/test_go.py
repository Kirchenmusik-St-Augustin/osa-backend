"""Tests for the public, unauthenticated go.-subdomain redirect router
(mounted at "/go" directly on `app`, see main.py). Uses the authenticated
/shorturls API to set up fixtures, exactly like a real admin would, then
hits the public /go/* endpoints with no Authorization header at all."""

import uuid


def _unique(base: str = "path") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _create_shorturl(client, make_user, *, path: str, target: str) -> None:
    user = make_user(password="correct-password", roles=["shorturls"])
    login = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        "/shorturls", json={"path": path, "target": target}, headers=headers
    )
    assert response.status_code == 201


class TestGoRoot:
    def test_redirects_to_hochamt_website(self, client):
        response = client.get("/go/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "https://www.hochamt.at"


class TestGoResolve:
    def test_known_path_redirects_to_normalized_target_no_auth_required(
        self, client, make_user
    ):
        path = _unique()
        _create_shorturl(client, make_user, path=path, target="example.org/foo")

        response = client.get(f"/go/{path}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "http://example.org/foo"

    def test_hit_is_counted(self, client, make_user):
        path = _unique()
        _create_shorturl(client, make_user, path=path, target="example.org")

        client.get(f"/go/{path}", follow_redirects=False)
        client.get(f"/go/{path}", follow_redirects=False)

        admin = make_user(password="correct-password", roles=["shorturls"])
        login = client.post(
            "/auth/login",
            data={"username": admin.email, "password": "correct-password"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        listed = client.get("/shorturls", headers=headers).json()["items"]
        item = next(i for i in listed if i["path"] == path)
        assert item["counter"] == 2
        assert item["latestcall_at"] is not None

    def test_unknown_path_returns_404(self, client):
        response = client.get(f"/go/{_unique()}", follow_redirects=False)
        assert response.status_code == 404

    def test_listall_is_not_a_public_dump(self, client):
        # Regression test for the closed security bug (Legacy's
        # GoController::go() special-cased "listAll" as an unauthenticated
        # dump of every stored target URL). With no shorturl actually
        # named "listAll", this must 404 like any other unknown path --
        # never return a 200 with a list of targets.
        response = client.get("/go/listAll", follow_redirects=False)
        assert response.status_code == 404

    def test_nested_path_with_slashes_is_supported(self, client, make_user):
        path = _unique("season/2026/concert")
        _create_shorturl(client, make_user, path=path, target="example.org/nested")

        response = client.get(f"/go/{path}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "http://example.org/nested"
