import pytest

from app.api.query_params import SEARCH_TERM_MAX_LENGTH

_SEARCH_ROUTES = [
    "/artists/search",
    "/ordinariumworks/search",
    "/propriumworks/search",
    "/scores/search",
    "/users/search",
    "/administrator/users/search",
]


@pytest.fixture
def headers(client, make_user) -> dict[str, str]:
    user = make_user(
        password="correct-password",
        roles=["planner", "disponent", "scores"],
        administrator=True,
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize("path", _SEARCH_ROUTES)
def test_a_search_term_at_the_maximum_length_is_accepted(client, headers, path):
    response = client.get(
        path, params={"q": "x" * SEARCH_TERM_MAX_LENGTH}, headers=headers
    )

    assert response.status_code == 200


@pytest.mark.parametrize("path", _SEARCH_ROUTES)
def test_a_search_term_above_the_maximum_length_is_rejected(client, headers, path):
    response = client.get(
        path, params={"q": "x" * (SEARCH_TERM_MAX_LENGTH + 1)}, headers=headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("path", _SEARCH_ROUTES)
@pytest.mark.parametrize("params", [{"q": ""}, {}])
def test_an_empty_or_missing_search_term_is_rejected(client, headers, path, params):
    response = client.get(path, params=params, headers=headers)

    assert response.status_code == 422
