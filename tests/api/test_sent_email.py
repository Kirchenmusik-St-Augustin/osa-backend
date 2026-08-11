import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.sent_email import SentEmail


def _unique(base: str = "Email") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(client, make_user, *, administrator: bool = False) -> dict[str, str]:
    user = make_user(password="correct-password", administrator=administrator)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_sent_email(db_session: Session, *, year: int, month: int) -> SentEmail:
    moment = datetime(year, month, 15, 10, 0, tzinfo=UTC)
    email = SentEmail(
        mail_from="noreply@example.test",
        to=f"{_unique('empfaenger')}@example.test",
        subject=_unique("Betreff"),
        body="<p>Inhalt</p>",
        mailer="smtp",
        created_at=moment,
        updated_at=moment,
    )
    db_session.add(email)
    db_session.commit()
    return email


class TestPermissionGuard:
    def test_list_requires_authentication(self, client):
        response = client.get(
            "/administrator/sent-emails", params={"year": 2026, "month": 1}
        )
        assert response.status_code == 401

    def test_list_rejects_disponent_without_administrator_flag(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get(
            "/administrator/sent-emails",
            params={"year": 2026, "month": 1},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_allows_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get(
            "/administrator/sent-emails",
            params={"year": 2026, "month": 1},
            headers=headers,
        )
        assert response.status_code == 200

    def test_show_requires_authentication(self, client):
        response = client.get("/administrator/sent-emails/1")
        assert response.status_code == 401


class TestListAndShow:
    def test_lists_only_the_requested_month(
        self, client, make_user, db_session: Session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        in_month = _make_sent_email(db_session, year=2026, month=7)
        _make_sent_email(db_session, year=2026, month=8)

        response = client.get(
            "/administrator/sent-emails",
            params={"year": 2026, "month": 7},
            headers=headers,
        )

        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert in_month.id in ids

    def test_show_returns_404_for_unknown_id(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get("/administrator/sent-emails/999999", headers=headers)
        assert response.status_code == 404

    def test_show_returns_full_detail_including_from_field(
        self, client, make_user, db_session: Session
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        email = _make_sent_email(db_session, year=2026, month=9)

        response = client.get(f"/administrator/sent-emails/{email.id}", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["from"] == "noreply@example.test"
        assert body["mailer"] == "smtp"


class TestNPlusOne:
    def test_list_query_count_does_not_scale_with_result_count(
        self, client, make_user, db_session: Session, count_queries
    ):
        headers = _auth_headers(client, make_user, administrator=True)
        for _ in range(3):
            _make_sent_email(db_session, year=2026, month=10)

        with count_queries() as small:
            small_response = client.get(
                "/administrator/sent-emails",
                params={"year": 2026, "month": 10},
                headers=headers,
            )

        for _ in range(5):
            _make_sent_email(db_session, year=2026, month=10)

        with count_queries() as large:
            large_response = client.get(
                "/administrator/sent-emails",
                params={"year": 2026, "month": 10},
                headers=headers,
            )

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()) > len(small_response.json())
        assert large.count == small.count
