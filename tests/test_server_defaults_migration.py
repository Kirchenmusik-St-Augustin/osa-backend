"""The server defaults of the required columns: what the migration leaves
behind, so a writer that is not this ORM does not have to supply them."""

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MIGRATION = "e1f2a3b4c5d6_add_server_defaults_to_required_columns.py"

# (table, column, default as PostgreSQL stores it)
_DEFAULTS = [
    ("users", "auth_locked", "false"),
    ("users", "administrator", "false"),
    ("artists", "composer", "false"),
    ("artists", "conductor", "false"),
    ("instruments", "active", "true"),
    ("voices", "active", "true"),
    ("choirjobs", "active", "true"),
    ("ordinariumworks", "demanding", "false"),
    ("propriumworks", "demanding", "false"),
    ("shorturls", "counter", "0"),
    ("performances", "choirjob_defaultfee", "35"),
    ("performances", "instrument_defaultfee", "60"),
    ("performances", "voice_defaultfee", "110"),
]
_IDS = [f"{table}.{column}" for table, column, _ in _DEFAULTS]


def _default_of(db: Session, table: str, column: str) -> str | None:
    return db.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar_one()


@pytest.mark.parametrize(("table", "column", "expected"), _DEFAULTS, ids=_IDS)
def test_the_column_has_its_server_default(
    db_session: Session, table: str, column: str, expected: str
):
    assert _default_of(db_session, table, column) == expected


def test_a_user_can_be_inserted_without_the_security_flags(db_session: Session):
    row = db_session.execute(
        text(
            "INSERT INTO users (surname, givenname) VALUES (:surname, 'Max') "
            "RETURNING auth_locked, administrator"
        ),
        {"surname": f"Muster-{uuid.uuid4().hex[:8]}"},
    ).one()

    assert tuple(row) == (False, False)


def test_a_short_link_starts_with_a_counter_of_zero(db_session: Session):
    counter = db_session.execute(
        text(
            "INSERT INTO shorturls (path, target) VALUES (:path, 'https://x.test') "
            "RETURNING counter"
        ),
        {"path": f"p-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()

    assert counter == 0


def test_an_artist_and_an_instrument_can_be_inserted_with_the_defaults(
    db_session: Session,
):
    artist = db_session.execute(
        text(
            "INSERT INTO artists (surname, givenname) VALUES (:surname, 'Vorname') "
            "RETURNING composer, conductor"
        ),
        {"surname": f"Komponist-{uuid.uuid4().hex[:8]}"},
    ).one()
    active = db_session.execute(
        text(
            "INSERT INTO instruments (name, sort_order) VALUES (:name, 0) "
            "RETURNING active"
        ),
        {"name": f"Instrument-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()

    assert tuple(artist) == (False, False)
    assert active is True


@pytest.mark.parametrize(
    ("table", "column"), [(t, c) for t, c, _ in _DEFAULTS], ids=_IDS
)
def test_the_downgrade_removes_the_default(
    db_session: Session, table: str, column: str
):
    run_migration(db_session, _MIGRATION, "downgrade")

    assert _default_of(db_session, table, column) is None
