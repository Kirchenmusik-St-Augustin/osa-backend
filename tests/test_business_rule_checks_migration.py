"""The database side of the artist, auth log, user agent and location rules:
what the migration leaves behind, and that its downgrade lifts the rules
again."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models.artist import Artist
from app.db.models.auth_log import AuthLog
from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.location import Location
from app.services import request_log_service
from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

_MIGRATION = "a7b8c9d0e1f2_enforce_artist_log_agent_and_color_rules.py"


def _rejected(db: Session, action: Callable[[], object]) -> bool:
    try:
        with db.begin_nested():
            action()
    except IntegrityError:
        return True
    return False


def _artist(db: Session, **overrides: object) -> Artist:
    fields: dict[str, object] = {
        "surname": f"Komponist-{uuid.uuid4().hex[:8]}",
        "givenname": "Vorname",
    }
    fields.update(overrides)
    artist = Artist(**fields)
    db.add(artist)
    db.flush()
    return artist


def _auth_log(db: Session, **overrides: object) -> AuthLog:
    fields: dict[str, object] = {"event": "Login", "fired_at": datetime.now(UTC)}
    fields.update(overrides)
    row = AuthLog(**fields)
    db.add(row)
    db.flush()
    return row


def _user_agent(db: Session, length: int) -> ClientUserAgent:
    row = ClientUserAgent(string="u" * length)
    db.add(row)
    db.flush()
    return row


def _location(db: Session, color: str) -> Location:
    row = Location(name=f"Ort-{uuid.uuid4().hex[:8]}", color=color)
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("name", ["surname", "givenname"])
def test_an_artist_without_a_name_is_refused(db_session: Session, name: str):
    assert _rejected(db_session, lambda: _artist(db_session, **{name: None}))


@pytest.mark.parametrize(
    ("birthyear", "deathyear"),
    [(1685, 1750), (1685, 1685), (1685, None), (None, 1750), (None, None)],
)
def test_an_artist_with_plausible_years_is_stored(
    db_session: Session, birthyear: int | None, deathyear: int | None
):
    artist = _artist(db_session, birthyear=birthyear, deathyear=deathyear)

    assert (artist.birthyear, artist.deathyear) == (birthyear, deathyear)


@pytest.mark.parametrize(
    ("birthyear", "deathyear"),
    [
        (999, None),
        (10000, None),
        (None, 999),
        (None, 10000),
        (1750, 1685),
        (0, 1700),
    ],
)
def test_an_artist_with_implausible_years_is_refused(
    db_session: Session, birthyear: int | None, deathyear: int | None
):
    assert _rejected(
        db_session,
        lambda: _artist(db_session, birthyear=birthyear, deathyear=deathyear),
    )


@pytest.mark.parametrize("column", ["event", "fired_at"])
def test_an_auth_log_row_needs_an_event_and_a_time(db_session: Session, column: str):
    assert _rejected(db_session, lambda: _auth_log(db_session, **{column: None}))
    assert _auth_log(db_session).event == "Login"


def test_a_user_agent_may_have_as_many_characters_as_the_service_stores(
    db_session: Session,
):
    longest = request_log_service._MAX_USER_AGENT_LENGTH

    assert len(_user_agent(db_session, longest).string) == longest


def test_a_longer_user_agent_is_refused_by_the_database(db_session: Session):
    longest = request_log_service._MAX_USER_AGENT_LENGTH

    assert _rejected(db_session, lambda: _user_agent(db_session, longest + 1))


@pytest.mark.parametrize("color", ["000000", "ff0000", "A1b2C3"])
def test_a_location_colour_of_six_hex_digits_is_stored(db_session: Session, color: str):
    assert _location(db_session, color).color == color


@pytest.mark.parametrize(
    "color", ["", "fff", "12345", "1234567", "zzzzzz", "12345g", "#ff0000", "ff0000\n"]
)
def test_any_other_location_colour_is_refused(db_session: Session, color: str):
    assert _rejected(db_session, lambda: _location(db_session, color))


def test_the_downgrade_lifts_the_rules_again(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")

    _artist(db_session, birthyear=1750, deathyear=1685)
    _artist(db_session, surname=None)
    _auth_log(db_session, event=None, fired_at=None)
    _user_agent(db_session, request_log_service._MAX_USER_AGENT_LENGTH + 1)
    _location(db_session, "red")


def test_the_upgrade_restores_the_rules_after_a_downgrade(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    run_migration(db_session, _MIGRATION)

    assert _rejected(db_session, lambda: _artist(db_session, surname=None))
    assert _rejected(db_session, lambda: _auth_log(db_session, event=None))
    assert _rejected(db_session, lambda: _location(db_session, "red"))
    assert _rejected(
        db_session,
        lambda: _user_agent(db_session, request_log_service._MAX_USER_AGENT_LENGTH + 1),
    )
    assert _rejected(
        db_session, lambda: _artist(db_session, birthyear=1750, deathyear=1685)
    )


def test_the_schema_has_the_constraints_the_models_declare(db_session: Session):
    names = set(
        db_session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('artists_years_check', 'client_user_agents_string_length_check', "
                "'locations_color_check')"
            )
        ).scalars()
    )

    assert names == {
        "artists_years_check",
        "client_user_agents_string_length_check",
        "locations_color_check",
    }
