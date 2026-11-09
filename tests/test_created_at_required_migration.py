"""The creation time is required on every table: what the migration does to
rows that have none, and that the database refuses to store another."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.migration_helpers import load_migration, run_migration

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MIGRATION = "f2a3b4c5d6e7_make_created_at_required.py"
_EARLIER = datetime(2020, 1, 1, tzinfo=UTC)
_TABLES = load_migration(_MIGRATION)._TABLES


def _insert_artist(db: Session, created_at, updated_at) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO artists (surname, givenname, created_at, updated_at) "
            "VALUES (:surname, 'Vorname', :created_at, :updated_at) RETURNING id"
        ),
        {
            "surname": f"Komponist-{uuid.uuid4().hex[:8]}",
            "created_at": created_at,
            "updated_at": updated_at,
        },
    ).scalar_one()


def _created_at(db: Session, artist_id: uuid.UUID) -> datetime:
    return db.execute(
        text("SELECT created_at FROM artists WHERE id = :id"), {"id": artist_id}
    ).scalar_one()


@pytest.mark.parametrize("table", _TABLES)
def test_the_column_is_required(db_session: Session, table: str):
    nullable = db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = 'created_at'"
        ),
        {"table": table},
    ).scalar_one()

    assert nullable == "NO"


def test_an_explicit_null_is_refused(db_session: Session):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        _insert_artist(db_session, None, None)


def test_the_upgrade_takes_the_missing_time_from_updated_at(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    artist_id = _insert_artist(db_session, None, _EARLIER)

    run_migration(db_session, _MIGRATION)

    assert _created_at(db_session, artist_id) == _EARLIER


def test_the_upgrade_takes_the_time_of_the_migration_without_updated_at(
    db_session: Session,
):
    run_migration(db_session, _MIGRATION, "downgrade")
    artist_id = _insert_artist(db_session, None, None)

    run_migration(db_session, _MIGRATION)

    assert datetime.now(UTC) - _created_at(db_session, artist_id) < timedelta(minutes=5)


def test_the_upgrade_keeps_a_creation_time_that_exists(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    artist_id = _insert_artist(db_session, _EARLIER, datetime.now(UTC))

    run_migration(db_session, _MIGRATION)

    assert _created_at(db_session, artist_id) == _EARLIER


@pytest.mark.parametrize("table", _TABLES)
def test_the_downgrade_allows_null_again(db_session: Session, table: str):
    run_migration(db_session, _MIGRATION, "downgrade")

    nullable = db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = 'created_at'"
        ),
        {"table": table},
    ).scalar_one()
    assert nullable == "YES"
