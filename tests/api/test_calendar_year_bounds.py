import pytest

from app.api.query_params import CALENDAR_YEAR_MAX, CALENDAR_YEAR_MIN

_MONTH_LIST_ROUTES = [
    "/performances",
    "/administrator/request-logs",
    "/administrator/sent-emails",
]


@pytest.fixture
def headers(client, make_user) -> dict[str, str]:
    user = make_user(password="correct-password", administrator=True)
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize("path", _MONTH_LIST_ROUTES)
@pytest.mark.parametrize("year", [CALENDAR_YEAR_MIN, CALENDAR_YEAR_MAX])
def test_a_year_at_the_edge_of_the_range_is_accepted(client, headers, path, year):
    response = client.get(path, params={"year": year, "month": 1}, headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize("path", _MONTH_LIST_ROUTES)
@pytest.mark.parametrize(
    "year", [CALENDAR_YEAR_MIN - 1, CALENDAR_YEAR_MAX + 1, 0, -5, 99999]
)
def test_a_year_outside_the_range_is_rejected(client, headers, path, year):
    response = client.get(path, params={"year": year, "month": 1}, headers=headers)

    assert response.status_code == 422
