from tests.booking_helpers import create_performance
from tests.login import login_headers


class TestPermissionGuard:
    def test_requires_authentication(self, client):
        response = client.get("/statistics")
        assert response.status_code == 401

    def test_any_authenticated_user_may_call_it(self, client, make_user):
        # No permission gate beyond being logged in.
        headers = login_headers(client, make_user)
        response = client.get("/statistics", headers=headers)
        assert response.status_code == 200


class TestGetStatistics:
    def test_returns_the_expected_shape(self, client, make_user):
        headers = login_headers(client, make_user)
        response = client.get("/statistics", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "users",
            "performances",
            "ordinariumworks",
            "propriumworks",
            "scores",
            "email",
        }
        assert body["email"] is None

    def test_the_mail_block_is_shown_to_holders_of_sent_email_view(
        self, client, make_user
    ):
        headers = login_headers(client, make_user, administrator=True)
        response = client.get("/statistics", headers=headers)

        body = response.json()
        assert set(body["email"].keys()) == {
            "active",
            "period_days",
            "threshold",
            "sent",
        }

    def test_the_counts_follow_the_stored_rows(self, client, make_user, db_session):
        headers = login_headers(client, make_user)
        before = client.get("/statistics", headers=headers).json()

        make_user()
        # Creates a performance together with its composer, location and
        # ordinarium work.
        create_performance(db_session)
        after = client.get("/statistics", headers=headers).json()

        assert after["users"] == before["users"] + 1
        assert after["performances"] == before["performances"] + 1
        assert after["ordinariumworks"] == before["ordinariumworks"] + 1
        assert after["propriumworks"] == before["propriumworks"]
        assert after["scores"] == before["scores"]


class TestMailBudgetVisibility:
    def test_a_member_does_not_see_the_mail_budget_but_still_the_counts(
        self, client, make_user
    ):
        headers = login_headers(client, make_user)
        response = client.get("/statistics", headers=headers)

        body = response.json()
        assert body["email"] is None
        assert isinstance(body["users"], int)
