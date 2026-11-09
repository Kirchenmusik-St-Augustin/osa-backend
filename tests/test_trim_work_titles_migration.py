"""The data cleanup of the migration that removes surrounding whitespace from
ordinarium and proprium work titles: what it trims and what it must leave
alone."""

import uuid
from typing import TYPE_CHECKING

import pytest

from app.db.models.artist import Artist
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.propriumwork import Propriumwork
from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MIGRATION = "d4e5f6a7b8c9_trim_work_titles.py"

_WORK_MODELS = [Ordinariumwork, Propriumwork]


def _artist(db: Session) -> Artist:
    artist = Artist(
        surname=f"Komponist-{uuid.uuid4().hex[:8]}", givenname="Vorname", composer=True
    )
    db.add(artist)
    db.flush()
    return artist


def _work(
    db: Session, model: type[Ordinariumwork | Propriumwork], artist: Artist, name: str
) -> Ordinariumwork | Propriumwork:
    work = model(name=name, artist_id=artist.id)
    db.add(work)
    db.flush()
    return work


@pytest.fixture(params=_WORK_MODELS, ids=lambda model: model.__tablename__)
def model(request: pytest.FixtureRequest) -> type[Ordinariumwork | Propriumwork]:
    return request.param


def test_padding_is_removed_from_a_title(db_session: Session, model):
    artist = _artist(db_session)
    trailing = _work(db_session, model, artist, "Requiem op. 9 ")
    both_sides = _work(db_session, model, artist, "\t Ave Maria \n")

    run_migration(db_session, _MIGRATION)

    assert trailing.name == "Requiem op. 9"
    assert both_sides.name == "Ave Maria"


def test_a_title_without_padding_and_inner_spaces_stay_as_they_are(
    db_session: Session, model
):
    artist = _artist(db_session)
    clean = _work(db_session, model, artist, "Messe in C")
    inner = _work(db_session, model, artist, "Sei stille  (Alt Arie)  ")

    run_migration(db_session, _MIGRATION)

    assert clean.name == "Messe in C"
    assert inner.name == "Sei stille  (Alt Arie)"


def test_the_same_title_of_another_composer_is_no_collision(db_session: Session, model):
    first = _work(db_session, model, _artist(db_session), "Ave Maria")
    second = _work(db_session, model, _artist(db_session), "Ave Maria ")

    run_migration(db_session, _MIGRATION)

    assert (first.name, second.name) == ("Ave Maria", "Ave Maria")


def test_a_padded_title_next_to_its_clean_twin_of_the_same_composer_is_left_alone(
    db_session: Session, model
):
    artist = _artist(db_session)
    clean = _work(db_session, model, artist, "Ave Maria")
    padded = _work(db_session, model, artist, "Ave Maria ")

    run_migration(db_session, _MIGRATION)

    assert (clean.name, padded.name) == ("Ave Maria", "Ave Maria ")


def test_two_padded_titles_of_one_composer_that_trim_alike_are_left_alone(
    db_session: Session, model
):
    artist = _artist(db_session)
    first = _work(db_session, model, artist, "Gloria ")
    second = _work(db_session, model, artist, " Gloria")

    run_migration(db_session, _MIGRATION)

    assert (first.name, second.name) == ("Gloria ", " Gloria")


def test_the_cleanup_of_one_table_does_not_touch_the_other(db_session: Session):
    artist = _artist(db_session)
    ordinarium = _work(db_session, Ordinariumwork, artist, "Credo ")
    proprium = _work(db_session, Propriumwork, artist, "Credo ")

    run_migration(db_session, _MIGRATION)

    assert (ordinarium.name, proprium.name) == ("Credo", "Credo")


def test_running_it_twice_changes_nothing_more(db_session: Session, model):
    artist = _artist(db_session)
    work = _work(db_session, model, artist, "Sanctus ")

    run_migration(db_session, _MIGRATION)
    run_migration(db_session, _MIGRATION)

    assert work.name == "Sanctus"


def test_the_downgrade_leaves_the_data_alone(db_session: Session, model):
    artist = _artist(db_session)
    work = _work(db_session, model, artist, "Agnus Dei ")

    run_migration(db_session, _MIGRATION, "downgrade")

    assert work.name == "Agnus Dei "
