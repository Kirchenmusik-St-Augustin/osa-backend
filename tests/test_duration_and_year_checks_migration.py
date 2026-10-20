"""The database side of the duration and year rules: the checks the migration
leaves behind, and what its upgrade does to a database that still has the
earlier, looser checks."""

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models.artist import Artist
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.propriumwork import Propriumwork
from app.schemas.score import ScoreRequest
from app.services import score_service
from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MIGRATION = "e5f6a7b8c9d0_tighten_duration_and_year_checks.py"
_YEARS = ("geboren", "gestorben", "jahr")
_WORK_MODELS = [Ordinariumwork, Propriumwork]


def _artist(db: Session) -> Artist:
    artist = Artist(surname=f"Komponist-{uuid.uuid4().hex[:8]}", givenname="Vorname")
    db.add(artist)
    db.flush()
    return artist


def _work(db: Session, model, duration: int | None):
    work = model(
        name=f"Werk-{uuid.uuid4().hex[:8]}", artist_id=_artist(db).id, duration=duration
    )
    db.add(work)
    db.flush()
    return work


def _score_id(db: Session) -> uuid.UUID:
    score = score_service.create_score(
        db,
        ScoreRequest.model_validate(
            {
                **score_service.get_defaults(),
                "kasten": "A",
                "boxnr": "1",
                "inhalt": "Partitur",
                "werk": f"Werk-{uuid.uuid4().hex[:8]}",
            }
        ),
    )
    return score.id


def _set_year(db: Session, score_id: uuid.UUID, column: str, value: int | None) -> None:
    db.execute(
        text(f"UPDATE scores SET {column} = :value WHERE id = :id"),  # noqa: S608
        {"value": value, "id": score_id},
    )


def _rejected(db: Session, action) -> bool:
    try:
        with db.begin_nested():
            action()
    except IntegrityError:
        return True
    return False


@pytest.fixture(params=_WORK_MODELS, ids=lambda model: model.__tablename__)
def model(request: pytest.FixtureRequest):
    return request.param


@pytest.mark.parametrize("duration", [1, 999, None])
def test_a_duration_in_range_is_stored(db_session: Session, model, duration):
    assert _work(db_session, model, duration).duration == duration


@pytest.mark.parametrize("duration", [0, -1, 1000])
def test_a_duration_out_of_range_is_refused_by_the_database(
    db_session: Session, model, duration
):
    assert _rejected(db_session, lambda: _work(db_session, model, duration))


@pytest.mark.parametrize("column", _YEARS)
def test_a_year_of_zero_is_refused_by_the_database(db_session: Session, column):
    score_id = _score_id(db_session)

    assert _rejected(db_session, lambda: _set_year(db_session, score_id, column, 0))
    assert _rejected(db_session, lambda: _set_year(db_session, score_id, column, -1))
    _set_year(db_session, score_id, column, 1)
    _set_year(db_session, score_id, column, None)


def _restore_the_looser_checks(db: Session) -> None:
    for table in ("ordinariumworks", "propriumworks"):
        db.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {table}_duration_check"))
    for column in _YEARS:
        db.execute(text(f"ALTER TABLE scores DROP CONSTRAINT scores_{column}_check"))
        db.execute(
            text(
                f"ALTER TABLE scores ADD CONSTRAINT scores_{column}_check "
                f"CHECK ({column} >= 0)"
            )
        )


def test_the_upgrade_turns_year_placeholders_into_null_and_tightens_the_checks(
    db_session: Session,
):
    score_id = _score_id(db_session)
    _restore_the_looser_checks(db_session)
    for column in _YEARS:
        _set_year(db_session, score_id, column, 0)

    run_migration(db_session, _MIGRATION)

    row = db_session.execute(
        text("SELECT geboren, gestorben, jahr FROM scores WHERE id = :id"),
        {"id": score_id},
    ).one()
    assert tuple(row) == (None, None, None)
    for column in _YEARS:
        assert _rejected(
            db_session, lambda c=column: _set_year(db_session, score_id, c, 0)
        )
    for model in _WORK_MODELS:
        assert _rejected(db_session, lambda m=model: _work(db_session, m, 0))


def test_the_upgrade_keeps_real_years_and_durations(db_session: Session):
    score_id = _score_id(db_session)
    _restore_the_looser_checks(db_session)
    _set_year(db_session, score_id, "geboren", 1685)
    ordinarium = _work(db_session, Ordinariumwork, 45)

    run_migration(db_session, _MIGRATION)

    db_session.expire_all()
    assert (
        db_session.execute(
            text("SELECT geboren FROM scores WHERE id = :id"), {"id": score_id}
        ).scalar_one()
        == 1685
    )
    assert ordinarium.duration == 45


def test_the_downgrade_restores_the_looser_rules(db_session: Session):
    score_id = _score_id(db_session)

    run_migration(db_session, _MIGRATION, "downgrade")

    for column in _YEARS:
        _set_year(db_session, score_id, column, 0)
        assert _rejected(
            db_session, lambda c=column: _set_year(db_session, score_id, c, -1)
        )
    for model in _WORK_MODELS:
        assert _work(db_session, model, 0).duration == 0
