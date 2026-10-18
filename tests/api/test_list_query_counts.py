"""N+1 guard for the list endpoints that return rows of one table: the number
of SQL statements must not grow with the number of rows."""

import uuid
from typing import TYPE_CHECKING

import pytest

from app.db.models.artist import Artist
from app.db.models.fee import Fee
from app.db.models.shorturl import Shorturl

if TYPE_CHECKING:
    from collections.abc import Callable


def _unique() -> str:
    return uuid.uuid4().hex[:10]


def _add_fee(db_session, _make_user) -> None:
    db_session.add(Fee(name=f"fee-{_unique()}", amount=10))


def _add_shorturl(db_session, _make_user) -> None:
    db_session.add(
        Shorturl(path=f"p-{_unique()}", target="https://example.org", counter=0)
    )


def _add_composer(db_session, _make_user) -> None:
    db_session.add(
        Artist(
            surname=f"KOMPONIST{_unique()}",
            givenname="Test",
            composer=True,
            conductor=False,
        )
    )


def _add_user(_db_session, make_user) -> None:
    make_user()


def _rows(payload: object) -> list[object]:
    if isinstance(payload, dict):
        return list(payload["items"])  # pyright: ignore[reportUnknownArgumentType]
    return list(payload)  # pyright: ignore[reportUnknownArgumentType, reportGeneralTypeIssues]


# (url, params, roles of the caller, administrator, seeder)
LIST_ENDPOINTS = [
    ("/fees", {}, ["disponent"], False, _add_fee),
    ("/shorturls", {}, ["shorturls"], False, _add_shorturl),
    ("/artists/composers", {}, ["planner"], False, _add_composer),
    ("/artists/search", {"q": "komponist"}, ["planner"], False, _add_composer),
    ("/userdirectory", {"type": "all"}, ["disponent"], False, _add_user),
    ("/administrator/users/search", {"q": "muster"}, [], True, _add_user),
]


def _login_headers(client, make_user, *, roles: list[str], administrator: bool):
    user = make_user(
        password="correct-password", roles=roles, administrator=administrator
    )
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    ("url", "params", "roles", "administrator", "seed"),
    LIST_ENDPOINTS,
    ids=[entry[0] for entry in LIST_ENDPOINTS],
)
def test_query_count_does_not_grow_with_the_number_of_rows(
    client,
    make_user,
    db_session,
    count_queries,
    url: str,
    params: dict[str, str],
    roles: list[str],
    administrator: bool,
    seed: Callable[..., None],
) -> None:
    headers = _login_headers(
        client, make_user, roles=roles, administrator=administrator
    )
    for _ in range(2):
        seed(db_session, make_user)
    db_session.commit()
    with count_queries() as small:
        small_response = client.get(url, params=params, headers=headers)

    for _ in range(8):
        seed(db_session, make_user)
    db_session.commit()
    with count_queries() as large:
        large_response = client.get(url, params=params, headers=headers)

    assert small_response.status_code == 200
    assert large_response.status_code == 200
    assert len(_rows(large_response.json())) > len(_rows(small_response.json()))
    assert large.count == small.count
