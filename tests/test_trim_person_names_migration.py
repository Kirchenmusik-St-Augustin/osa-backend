"""The data cleanup of the migration that removes surrounding whitespace from
user and artist names: what it trims, what it must leave alone and the one
collision it resolves."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.db.models.artist import Artist
from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.user import User

_MIGRATION = "c3d4e5f6a7b8_trim_person_names.py"


def _run_upgrade(db: Session) -> None:
    run_migration(db, _MIGRATION)


def _marker() -> str:
    return uuid.uuid4().hex[:10]


def _user(
    make_user: Callable[..., User],
    surname: str,
    givenname: str,
    *,
    deleted: bool = False,
) -> User:
    user = make_user()
    user.surname = surname
    user.givenname = givenname
    if deleted:
        user.deleted_at = datetime.now(UTC)
    return user


def _names(user: User) -> tuple[str, str]:
    return user.surname, user.givenname


def test_padding_is_removed_from_user_names(db_session, make_user):
    marker = _marker()
    padded = _user(make_user, f"  {marker} ", f"Anna{marker} ")
    tabs = _user(make_user, f"\t{marker}2\n", f"\nBerta{marker}\t")

    _run_upgrade(db_session)

    assert _names(padded) == (marker, f"Anna{marker}")
    assert _names(tabs) == (f"{marker}2", f"Berta{marker}")


def test_names_without_padding_stay_as_they_are(db_session, make_user):
    marker = _marker()
    inner_spaces = _user(make_user, f"{marker}", f"Maria  Theresa{marker}")

    _run_upgrade(db_session)

    assert _names(inner_spaces) == (marker, f"Maria  Theresa{marker}")


def test_a_deleted_account_is_trimmed_like_an_active_one(db_session, make_user):
    marker = _marker()
    deleted = _user(make_user, f"{marker} ", f"Carl{marker}", deleted=True)

    _run_upgrade(db_session)

    assert _names(deleted) == (marker, f"Carl{marker}")


def test_a_deleted_duplicate_is_marked_and_the_active_account_is_trimmed(
    db_session, make_user
):
    marker = _marker()
    deleted = _user(make_user, marker, f"Dora{marker}", deleted=True)
    active = _user(make_user, marker, f"Dora{marker} ")
    other_person = _user(make_user, marker, f"Dorothea{marker}")

    _run_upgrade(db_session)

    assert _names(deleted) == (marker, f"Dora{marker}_geloescht")
    assert _names(active) == (marker, f"Dora{marker}")
    assert _names(other_person) == (marker, f"Dorothea{marker}")
    assert deleted.deleted_at is not None
    assert active.deleted_at is None


def test_two_deleted_namesakes_are_left_alone(db_session, make_user):
    marker = _marker()
    unpadded = _user(make_user, marker, f"Ida{marker}", deleted=True)
    padded = _user(make_user, marker, f"Ida{marker} ", deleted=True)

    _run_upgrade(db_session)

    assert _names(unpadded) == (marker, f"Ida{marker}")
    assert _names(padded) == (marker, f"Ida{marker} ")


def test_a_padded_active_account_next_to_an_active_namesake_is_left_alone(
    db_session, make_user
):
    marker = _marker()
    unpadded = _user(make_user, marker, f"Emil{marker}")
    padded = _user(make_user, marker, f"Emil{marker} ")

    _run_upgrade(db_session)

    assert _names(unpadded) == (marker, f"Emil{marker}")
    assert _names(padded) == (marker, f"Emil{marker} ")


def test_two_padded_accounts_that_trim_to_one_name_are_left_alone(
    db_session, make_user
):
    marker = _marker()
    first = _user(make_user, marker, f"Fritz{marker} ")
    second = _user(make_user, marker, f" Fritz{marker}")

    _run_upgrade(db_session)

    assert _names(first) == (marker, f"Fritz{marker} ")
    assert _names(second) == (marker, f" Fritz{marker}")


def test_running_the_cleanup_twice_changes_nothing_more(db_session, make_user):
    marker = _marker()
    deleted = _user(make_user, marker, f"Gerda{marker}", deleted=True)
    active = _user(make_user, marker, f"Gerda{marker} ")

    _run_upgrade(db_session)
    _run_upgrade(db_session)

    assert _names(deleted) == (marker, f"Gerda{marker}_geloescht")
    assert _names(active) == (marker, f"Gerda{marker}")


def _artist(db: Session, surname: str, givenname: str) -> Artist:
    artist = Artist(surname=surname, givenname=givenname)
    db.add(artist)
    return artist


def test_padding_is_removed_from_artist_names(db_session: Session):
    marker = _marker()
    padded = _artist(db_session, f" Bach{marker} ", f"Johann{marker}  ")

    _run_upgrade(db_session)

    assert (padded.surname, padded.givenname) == (f"Bach{marker}", f"Johann{marker}")


def test_artist_names_that_would_collide_or_are_blank_stay_as_they_are(
    db_session: Session,
):
    marker = _marker()
    unpadded = _artist(db_session, f"Haydn{marker}", f"Joseph{marker}")
    padded = _artist(db_session, f"Haydn{marker}", f"Joseph{marker} ")
    no_given_name = _artist(db_session, f"Tallis{marker}", "")

    _run_upgrade(db_session)

    assert (unpadded.surname, unpadded.givenname) == (
        f"Haydn{marker}",
        f"Joseph{marker}",
    )
    assert (padded.surname, padded.givenname) == (f"Haydn{marker}", f"Joseph{marker} ")
    assert (no_given_name.surname, no_given_name.givenname) == (f"Tallis{marker}", "")


def test_the_downgrade_leaves_the_data_alone(db_session, make_user):
    marker = _marker()
    padded = _user(make_user, marker, f"Hans{marker} ")
    run_migration(db_session, _MIGRATION, "downgrade")

    assert _names(padded) == (marker, f"Hans{marker} ")
