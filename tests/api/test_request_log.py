import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.request_log import RequestLog


def _unique(base: str = "Log") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(client, make_user, *, administrator: bool = False) -> dict[str, str]:
    user = make_user(password="correct-password", administrator=administrator)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_entry(
    db_session: Session, *, user_id: int | None, year: int, month: int
) -> RequestLog:
    moment = datetime(year, month, 12, 9, 0, tzinfo=UTC)
    entry = RequestLog(
        client_ip="127.0.0.1",
        client_ips="[]",
        client_user_agent_id=None,
        user_id=user_id,
        request_method="GET",
        request_path=_unique("/some/path"),
        request_input="{}",
        response_status=200,
        response_content="null",
        memory_usage=1,
        created_at=moment,
        updated_at=moment,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


class TestPermissionGuard:
    def test_list_users_requires_authentication(self, client):
        response = client.get(
            "/administrator/request-logs", params={"year": 2026, "month": 1}
        )
        assert response.status_code == 401

    def test_list_users_rejects_disponent_without_administrator_flag(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user)
        response = client.get(
            "/administrator/request-logs",
            params={"year": 2026, "month": 1},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_users_allows_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get(
            "/administrator/request-logs",
            params={"year": 2026, "month": 1},
            headers=headers,
        )
        assert response.status_code == 200

    def test_user_detail_requires_authentication(self, client):
        response = client.get(
            "/administrator/request-logs/users/1",
            params={"year": 2026, "month": 1},
        )
        assert response.status_code == 401

    def test_show_requires_authentication(self, client):
        response = client.get("/administrator/request-logs/1")
        assert response.status_code == 401


class TestUserFlow:
    def test_lists_only_users_with_entries_in_the_requested_month(
        self, client, make_user, db_session: Session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        _make_entry(db_session, user_id=target.id, year=2026, month=11)

        response = client.get(
            "/administrator/request-logs",
            params={"year": 2026, "month": 11},
            headers=headers,
        )

        assert response.status_code == 200
        assert target.id in [item["id"] for item in response.json()]

    def test_user_detail_returns_entries_for_that_user_and_month(
        self, client, make_user, db_session: Session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        entry = _make_entry(db_session, user_id=target.id, year=2026, month=12)

        response = client.get(
            f"/administrator/request-logs/users/{target.id}",
            params={"year": 2026, "month": 12},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["username"] == f"{target.surname}, {target.givenname}"
        assert [item["id"] for item in body["entries"]] == [entry.id]

    def test_user_detail_returns_404_for_unknown_user(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get(
            "/administrator/request-logs/users/999999",
            params={"year": 2026, "month": 1},
            headers=headers,
        )
        assert response.status_code == 404

    def test_show_returns_404_for_unknown_id(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get("/administrator/request-logs/999999", headers=headers)
        assert response.status_code == 404

    def test_show_returns_full_detail(self, client, make_user, db_session: Session):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        entry = _make_entry(db_session, user_id=target.id, year=2026, month=10)

        response = client.get(
            f"/administrator/request-logs/{entry.id}", headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == entry.id
        assert body["user_name"] == f"{target.surname}, {target.givenname}"


class TestNPlusOne:
    def test_list_users_query_count_does_not_scale_with_result_count(
        self, client, make_user, db_session: Session, count_queries
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        for _ in range(3):
            _make_entry(db_session, user_id=make_user().id, year=2026, month=9)

        with count_queries() as small:
            small_response = client.get(
                "/administrator/request-logs",
                params={"year": 2026, "month": 9},
                headers=headers,
            )

        for _ in range(5):
            _make_entry(db_session, user_id=make_user().id, year=2026, month=9)

        with count_queries() as large:
            large_response = client.get(
                "/administrator/request-logs",
                params={"year": 2026, "month": 9},
                headers=headers,
            )

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()) > len(small_response.json())
        assert large.count == small.count

    def test_user_detail_query_count_does_not_scale_with_entry_count(
        self, client, make_user, db_session: Session, count_queries
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        target = make_user()
        for _ in range(3):
            _make_entry(db_session, user_id=target.id, year=2026, month=8)

        with count_queries() as small:
            small_response = client.get(
                f"/administrator/request-logs/users/{target.id}",
                params={"year": 2026, "month": 8},
                headers=headers,
            )

        for _ in range(5):
            _make_entry(db_session, user_id=target.id, year=2026, month=8)

        with count_queries() as large:
            large_response = client.get(
                f"/administrator/request-logs/users/{target.id}",
                params={"year": 2026, "month": 8},
                headers=headers,
            )

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()["entries"]) > len(
            small_response.json()["entries"]
        )
        assert large.count == small.count
