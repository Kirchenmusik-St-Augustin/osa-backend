"""The database side of the position quantities, the recipient count of the
sent mails and the indexes on the log times: what the migration leaves
behind."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core import mailer
from app.db.database import engine
from app.db.models.artist import Artist
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from tests.migration_helpers import run_migration
from tests.sent_emails import sent_email

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.instrument import Instrument
    from app.db.models.sent_email import SentEmail

_MIGRATION = "d0e1f2a3b4c5_check_quantities_count_recipients_index_logs.py"


def _ordinariumwork(db: Session) -> Ordinariumwork:
    artist = Artist(surname=f"Komponist-{uuid.uuid4().hex[:8]}", givenname="Vorname")
    db.add(artist)
    db.flush()
    work = Ordinariumwork(name=f"Werk-{uuid.uuid4().hex[:8]}", artist_id=artist.id)
    db.add(work)
    db.flush()
    return work


def _performance(db: Session) -> Performance:
    location = Location(name=f"Ort-{uuid.uuid4().hex[:8]}", address="Adresse 1")
    db.add(location)
    db.flush()
    performance = Performance(
        schedule=datetime(2099, 1, 1, 12, 0),  # noqa: DTZ001 -- naive on purpose
        location_id=location.id,
        ordinariumwork_id=_ordinariumwork(db).id,
    )
    db.add(performance)
    db.flush()
    return performance


def _rejected(db: Session, action: Callable[[], object]) -> bool:
    try:
        with db.begin_nested():
            action()
    except IntegrityError:
        return True
    return False


def _ordinarium_position(db: Session, instrument: Instrument, quantity: int):
    db.add(
        OrdinariumworkPosition(
            ordinariumwork_id=_ordinariumwork(db).id,
            instrument_id=instrument.id,
            quantity=quantity,
        )
    )
    db.flush()


def _performance_position(db: Session, instrument: Instrument, quantity: int):
    db.add(
        PerformancePosition(
            performance_id=_performance(db).id,
            instrument_id=instrument.id,
            quantity=quantity,
        )
    )
    db.flush()


_POSITION_WRITERS = [_ordinarium_position, _performance_position]
_POSITION_IDS = ["ordinariumwork_positions", "performance_positions"]


@pytest.mark.parametrize("write", _POSITION_WRITERS, ids=_POSITION_IDS)
@pytest.mark.parametrize("quantity", [1, 7, 99])
def test_a_quantity_from_one_to_ninety_nine_is_stored(
    db_session: Session, make_instrument, write, quantity: int
):
    write(db_session, make_instrument(), quantity)


@pytest.mark.parametrize("write", _POSITION_WRITERS, ids=_POSITION_IDS)
@pytest.mark.parametrize("quantity", [0, -1, 100])
def test_any_other_quantity_is_refused_by_the_database(
    db_session: Session, make_instrument, write, quantity: int
):
    instrument = make_instrument()

    assert _rejected(db_session, lambda: write(db_session, instrument, quantity))


def _mail(db: Session, **addresses: str | None) -> SentEmail:
    row = sent_email(subject="Betreff", body="Text", **addresses)
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def _reference_count(value: str | None) -> int:
    """The count the mail kill switch used to compute in Python."""
    if not value:
        return 0
    return len([part for part in value.split(",") if part.strip()])


_ADDRESS_LISTS = [
    None,
    "",
    " ",
    "\t",
    "a@example.com",
    " a@example.com ",
    "a@example.com, b@example.com",
    "a@example.com,b@example.com",
    "a@example.com ,  b@example.com",
    "a@example.com,",
    ",a@example.com",
    "a@example.com,,b@example.com",
    "a@example.com, ,b@example.com",
    "a@example.com,\tb@example.com",
    ",",
    " , ",
    "a@example.com, b@example.com, c@example.com, d@example.com",
]


@pytest.mark.parametrize("addresses", _ADDRESS_LISTS)
def test_the_stored_recipient_count_equals_the_former_python_count(
    db_session: Session, addresses: str | None
):
    row = _mail(db_session, to=addresses, cc=addresses, bcc=addresses)

    assert row.recipient_count == 3 * _reference_count(addresses)


def test_the_recipient_count_adds_the_three_lists(db_session: Session):
    row = _mail(db_session, to="a@example.com", cc="b@example.com, c@example.com")

    assert row.recipient_count == 3


def test_the_recipient_count_follows_an_update(db_session: Session):
    row = _mail(db_session, to="a@example.com")

    row.bcc = "b@example.com, c@example.com"
    db_session.flush()
    db_session.refresh(row)

    assert row.recipient_count == 3


def test_the_kill_switch_sums_the_stored_recipient_counts(db_session: Session):
    db_session.execute(text("DELETE FROM sent_emails"))
    _mail(db_session, to="a@example.com, b@example.com")
    _mail(db_session, bcc="c@example.com, d@example.com, e@example.com")

    assert mailer.get_kill_switch_status(db_session).sent == 5


def test_the_kill_switch_counts_only_the_mails_of_its_window(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAIL_KILL_SWITCH_PERIOD_DAYS", "30")
    db_session.execute(text("DELETE FROM sent_emails"))
    _mail(db_session, to="a@example.com")
    old = _mail(db_session, to="b@example.com, c@example.com")
    old.created_at = datetime.now(UTC) - timedelta(days=31)
    db_session.flush()

    assert mailer.get_kill_switch_status(db_session).sent == 1


def test_the_kill_switch_reports_zero_without_mails(db_session: Session):
    db_session.execute(text("DELETE FROM sent_emails"))

    status = mailer.get_kill_switch_status(db_session)

    assert (status.sent, status.active) == (0, False)


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("sent_emails", "sent_emails_created_at_index"),
        ("request_logs", "request_logs_created_at_index"),
    ],
)
def test_the_log_time_is_indexed(table: str, index: str):
    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes(table)}

    assert indexes[index] == ["created_at"]


def test_the_downgrade_removes_checks_column_and_indexes(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")

    columns = {
        c["name"] for c in inspect(db_session.connection()).get_columns("sent_emails")
    }
    names = set(
        db_session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('ordinariumwork_positions_quantity_check', "
                "'performance_positions_quantity_check')"
            )
        ).scalars()
    )
    indexes = set(
        db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE indexname IN "
                "('sent_emails_created_at_index', 'request_logs_created_at_index')"
            )
        ).scalars()
    )
    assert "recipient_count" not in columns
    assert names == set()
    assert indexes == set()
