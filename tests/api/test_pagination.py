import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from app.schemas.artist import ArtistRequest
from app.schemas.coreelement import CoreelementRequest, CoreelementType
from app.schemas.fee import FeeRequest
from app.schemas.pagination import MAX_PAGE_OFFSET, MAX_PAGE_SIZE
from app.services import artist_service, coreelement_service, fee_service
from tests.sent_emails import sent_email

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.user import User

_SENT_EMAIL_MONTH = {"year": 2031, "month": 2}


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _seed_fees(db: Session, _make_user: Callable[..., User]) -> None:
    for _ in range(3):
        fee_service.create_fee(db, FeeRequest(name=_unique("Gage"), amount=10))


def _seed_composers(db: Session, _make_user: Callable[..., User]) -> None:
    for _ in range(3):
        artist_service.create_artist(
            db,
            ArtistRequest(
                surname=_unique("Komponist"),
                givenname=_unique("Vorname"),
                composer=True,
            ),
        )


def _seed_coreelements(db: Session, _make_user: Callable[..., User]) -> None:
    for _ in range(3):
        coreelement_service.create_coreelement(
            db, CoreelementType.instrument, CoreelementRequest(name=_unique("Posaune"))
        )


def _seed_deleted_users(db: Session, make_user: Callable[..., User]) -> None:
    for _ in range(3):
        make_user().deleted_at = datetime.now(UTC)
    db.commit()


def _seed_users(_db: Session, make_user: Callable[..., User]) -> None:
    for _ in range(3):
        make_user()


def _seed_sent_emails(db: Session, _make_user: Callable[..., User]) -> None:
    for minute in range(3):
        moment = datetime(2031, 2, 15, 10, minute, tzinfo=UTC)
        db.add(
            sent_email(
                mail_from="noreply@example.test",
                to=f"{_unique('empfaenger')}@example.test",
                subject=_unique("Betreff"),
                body="<p>Inhalt</p>",
                mailer="smtp",
                created_at=moment,
                updated_at=moment,
            )
        )
    db.commit()


# name -> (path of the route for the calling user, extra query parameters,
# seeding function). The two requests-and-bookings routes need performances
# with bookings to hold several rows, their paging is covered in
# tests/services/test_booking_service.py.
_SEEDED_ROUTES = {
    "fees": (lambda _user: "/fees", {}, _seed_fees),
    "composers": (lambda _user: "/artists/composers", {}, _seed_composers),
    "coreelements": (
        lambda _user: "/coreelements/instrument",
        {},
        _seed_coreelements,
    ),
    "deleted-users": (
        lambda _user: "/administrator/users/deleted",
        {},
        _seed_deleted_users,
    ),
    "sent-emails": (
        lambda _user: "/administrator/sent-emails",
        _SENT_EMAIL_MONTH,
        _seed_sent_emails,
    ),
    "userdirectory": (lambda _user: "/userdirectory", {}, _seed_users),
}

_UNSEEDED_ROUTES = {
    "support-requests": (lambda _user: "/support/requests-and-bookings", {}),
    "user-requests": (lambda user: f"/users/{user.id}/requests-and-bookings", {}),
}

_ALL_ROUTES = {
    **{name: (path, params) for name, (path, params, _seed) in _SEEDED_ROUTES.items()},
    **_UNSEEDED_ROUTES,
}


@pytest.fixture
def caller(client, make_user) -> tuple[dict[str, str], User]:
    user = make_user(
        password="correct-password",
        roles=["disponent", "planner"],
        administrator=True,
    )
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user


@pytest.mark.parametrize("route", sorted(_ALL_ROUTES))
def test_a_list_is_answered_with_the_envelope_and_the_default_page(
    client, caller, route
):
    headers, user = caller
    path, params = _ALL_ROUTES[route]

    response = client.get(path(user), params=params, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["limit"] == MAX_PAGE_SIZE
    assert body["offset"] == 0
    assert body["total"] >= len(body["items"])


@pytest.mark.parametrize("route", sorted(_ALL_ROUTES))
@pytest.mark.parametrize(
    "paging",
    [
        {"limit": 0},
        {"limit": MAX_PAGE_SIZE + 1},
        {"limit": -1},
        {"offset": -1},
        {"offset": MAX_PAGE_OFFSET + 1},
        {"offset": 10**30},
        {"limit": "many"},
    ],
)
def test_a_page_outside_the_bounds_is_rejected(client, caller, route, paging):
    headers, user = caller
    path, params = _ALL_ROUTES[route]

    response = client.get(path(user), params={**params, **paging}, headers=headers)

    assert response.status_code == 422


@pytest.mark.parametrize("route", sorted(_ALL_ROUTES))
@pytest.mark.parametrize(
    "paging", [{"limit": MAX_PAGE_SIZE, "offset": MAX_PAGE_OFFSET}, {"limit": 1}]
)
def test_a_page_at_the_edge_of_the_bounds_is_accepted(client, caller, route, paging):
    headers, user = caller
    path, params = _ALL_ROUTES[route]

    response = client.get(path(user), params={**params, **paging}, headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize("route", sorted(_SEEDED_ROUTES))
def test_pages_follow_each_other_without_gaps_or_repeats(
    client, caller, db_session, make_user, route
):
    headers, user = caller
    path, params, seed = _SEEDED_ROUTES[route]
    seed(db_session, make_user)
    url = path(user)

    everything = client.get(url, params=params, headers=headers).json()
    first = client.get(
        url, params={**params, "limit": 2, "offset": 0}, headers=headers
    ).json()
    second = client.get(
        url, params={**params, "limit": 2, "offset": 2}, headers=headers
    ).json()
    last = client.get(
        url,
        params={**params, "limit": 2, "offset": everything["total"] - 1},
        headers=headers,
    ).json()
    beyond = client.get(
        url,
        params={**params, "limit": 2, "offset": everything["total"]},
        headers=headers,
    ).json()

    assert everything["total"] >= 3
    assert len(first["items"]) == 2
    assert first["total"] == second["total"] == everything["total"]
    assert (first["limit"], first["offset"]) == (2, 0)
    assert (second["limit"], second["offset"]) == (2, 2)
    assert first["items"] + second["items"] == everything["items"][:4]
    assert len(last["items"]) == 1
    assert beyond["items"] == []
    assert beyond["total"] == everything["total"]
