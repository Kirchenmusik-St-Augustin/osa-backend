import itertools
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.propriumelement import Propriumelement
from app.db.models.propriumwork import Propriumwork
from app.db.models.user import User
from app.db.models.voice import Voice
from app.schemas.artist import ArtistRequest
from app.schemas.performance import (
    PerformancePositionInput,
    PerformancePropriumEntryInput,
    PerformanceRehearsalInput,
    PerformanceRequest,
    PerformanceSetupInput,
)
from app.services import artist_service, performance_service

_schedule_counter = itertools.count(2)


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _unique_schedule() -> datetime:
    """Each call advances by a whole day, so tests never collide on the
    (location, hour) uniqueness rule unless they deliberately reuse a
    schedule to test that rule. Normalized to a fixed minute/second so
    hour-boundary arithmetic in collision tests (+/- N minutes) is
    deterministic regardless of the wall-clock minute the suite happens to
    run at (an earlier version of this helper was flaky right around the
    top of an hour for exactly that reason). Naive local_now()-based, not
    datetime.now(UTC) -- `schedule` is a naive wall-clock value, and
    comparing it against an aware datetime raises TypeError (see
    app.core.datetime_utils.local_now())."""
    days_ahead = next(_schedule_counter)
    base = local_now() + timedelta(days=days_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


def _make_artist(
    db_session: Session, *, composer: bool = False, conductor: bool = False
) -> int:
    artist = artist_service.create_artist(
        db_session,
        ArtistRequest(
            surname=_unique("Artist"),
            givenname=_unique("First"),
            composer=composer,
            conductor=conductor,
        ),
    )
    return artist.id


def _make_location(db_session: Session) -> Location:
    now = datetime.now(UTC)
    location = Location(
        name=_unique("Location"),
        order=0,
        address="Adresse 1",
        color="000000",
        created_at=now,
        updated_at=now,
    )
    db_session.add(location)
    db_session.commit()
    return location


def _make_ordinariumwork(db_session: Session, composer_id: int) -> Ordinariumwork:
    now = datetime.now(UTC)
    work = Ordinariumwork(
        name=_unique("Werk"),
        artist_id=composer_id,
        demanding=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(work)
    db_session.commit()
    return work


def _make_propriumelement(db_session: Session) -> Propriumelement:
    now = datetime.now(UTC)
    element = Propriumelement(
        name=_unique("Element"), order=0, created_at=now, updated_at=now
    )
    db_session.add(element)
    db_session.commit()
    return element


def _make_propriumwork(
    db_session: Session, composer_id: int, *, demanding: bool = False
) -> Propriumwork:
    now = datetime.now(UTC)
    work = Propriumwork(
        name=_unique("Proprium"),
        artist_id=composer_id,
        demanding=demanding,
        created_at=now,
        updated_at=now,
    )
    db_session.add(work)
    db_session.commit()
    return work


def _make_instrument(db_session: Session) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=_unique("Instrument"), order=0, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def _make_voice(db_session: Session) -> Voice:
    now = datetime.now(UTC)
    voice = Voice(name=_unique("Voice"), order=0, created_at=now, updated_at=now)
    db_session.add(voice)
    db_session.commit()
    return voice


def _make_choirjob(db_session: Session) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=_unique("Choirjob"), order=0, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


def _move_to_past(db_session: Session, performance_id: int) -> None:
    performance = db_session.execute(
        select(Performance).where(Performance.id == performance_id)
    ).scalar_one()
    performance.schedule = local_now() - timedelta(days=1)
    db_session.commit()


def _request(
    location_id: int,
    ordinariumwork_id: int,
    schedule: datetime | None = None,
    setup: PerformanceSetupInput | None = None,
    **overrides: object,
) -> PerformanceRequest:
    defaults: dict[str, object] = {
        "schedule": schedule or _unique_schedule(),
        "location_id": location_id,
        "ordinariumwork_id": ordinariumwork_id,
        "artist_id": None,
        "description": None,
        "choirjob_defaultfee": 35,
        "instrument_defaultfee": 60,
        "voice_defaultfee": 110,
        "extracost_amount": None,
        "extracost_description": None,
        "setup": setup or PerformanceSetupInput(),
        "proprium": [],
        "rehearsals": [],
    }
    defaults.update(overrides)
    return PerformanceRequest(**defaults)  # type: ignore[arg-type]


class TestListPerformancesForMonth:
    def test_returns_only_performances_in_the_given_month_ordered_by_schedule(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        # A far-future, dedicated month keeps this test isolated from
        # _unique_schedule()'s day-incrementing performances elsewhere in
        # this shared, non-rolled-back test DB (see conftest.py).
        composer = artist_service.create_artist(
            db_session,
            ArtistRequest(surname="Haydn", givenname=_unique("Joseph"), composer=True),
        )
        conductor = artist_service.create_artist(
            db_session,
            ArtistRequest(surname="Ortner", givenname="Erwin", conductor=True),
        )
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer.id)
        element = _make_propriumelement(db_session)
        propriumwork = _make_propriumwork(db_session, composer.id, demanding=True)

        later = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=datetime(2031, 6, 20, 11, 0),  # noqa: DTZ001 -- naive on purpose
                artist_id=conductor.id,
                proprium=[
                    PerformancePropriumEntryInput(
                        propriumelement_id=element.id, propriumwork_id=propriumwork.id
                    )
                ],
                rehearsals=[
                    PerformanceRehearsalInput(
                        schedule=datetime(2031, 6, 19, 18, 0),  # noqa: DTZ001 -- naive on purpose
                        comment="GP",
                    )
                ],
            ),
        )
        earlier = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=datetime(2031, 6, 6, 9, 0),  # noqa: DTZ001 -- naive on purpose
            ),
        )
        # A different month must not appear in the June 2031 result.
        performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=datetime(2031, 7, 6, 9, 0),  # noqa: DTZ001 -- naive on purpose
            ),
        )

        user = make_user()
        items = performance_service.list_performances_for_month(
            db_session, 2031, 6, user.id
        )

        assert [item.id for item in items] == [earlier.id, later.id]
        later_item = items[1]
        assert later_item.location.id == location.id
        assert later_item.artist_name == "ORTNER, Erwin"
        assert (
            later_item.ordinariumwork_artist_name
            == f"{composer.surname}, {composer.givenname}"
        )
        assert later_item.demanding_proprium is True
        assert later_item.rehearsals[0].comment == "GP"

    def test_empty_month_returns_empty_list(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        user = make_user()
        result = performance_service.list_performances_for_month(
            db_session, 1999, 1, user.id
        )
        assert result == []


class TestCreatePerformance:
    def test_basic_create_returns_response(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)

        response = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )

        assert response.location_id == location.id
        assert response.ordinariumwork_id == work.id
        assert response.instrument_defaultfee == 60

    def test_rejects_schedule_before_tomorrow(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(location.id, work.id, schedule=local_now()),
            )

        assert exc_info.value.errors == [
            ("schedule", "Aufführungs-Datum muss frühestens morgen sein.")
        ]

    def test_rejects_unknown_location(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        work = _make_ordinariumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session, _request(999999, work.id)
            )

        assert exc_info.value.errors == [("location_id", "Ort wurde nicht gefunden.")]

    def test_rejects_unknown_ordinariumwork(self, db_session: Session):
        location = _make_location(db_session)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session, _request(location.id, 999999)
            )

        assert exc_info.value.errors == [
            ("ordinariumwork_id", "Ordinarium-Komposition wurde nicht gefunden.")
        ]

    def test_rejects_unknown_conductor(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session, _request(location.id, work.id, artist_id=999999)
            )

        assert exc_info.value.errors == [
            ("artist_id", "Dirigent wurde nicht gefunden.")
        ]

    def test_rejects_unknown_instrument_in_setup(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        setup = PerformanceSetupInput(
            instruments=[PerformancePositionInput(id=999999, quantity=1)]
        )

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session, _request(location.id, work.id, setup=setup)
            )

        assert exc_info.value.errors == [
            ("setup", "instruments: Element nicht gefunden.")
        ]

    def test_rejects_duplicate_position_entry(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        instrument = _make_instrument(db_session)
        setup = PerformanceSetupInput(
            instruments=[
                PerformancePositionInput(id=instrument.id, quantity=1),
                PerformancePositionInput(id=instrument.id, quantity=2),
            ]
        )

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session, _request(location.id, work.id, setup=setup)
            )

        assert exc_info.value.errors == [("setup", "instruments: doppelter Eintrag.")]

    def test_rejects_unknown_propriumwork(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        element = _make_propriumelement(db_session)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    proprium=[
                        PerformancePropriumEntryInput(
                            propriumelement_id=element.id, propriumwork_id=999999
                        )
                    ],
                ),
            )

        assert exc_info.value.errors == [("proprium", "Werk wurde nicht gefunden.")]

    def test_accepts_choirjob_position(self, db_session: Session):
        """Unlike Ordinariumwork, Performance's setup legitimately includes
        choirjobs (confirmed live, see project_osa_performance_domain_research)."""
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        choirjob = _make_choirjob(db_session)
        setup = PerformanceSetupInput(
            choirjobs=[PerformancePositionInput(id=choirjob.id, quantity=2)]
        )

        response = performance_service.create_performance(
            db_session, _request(location.id, work.id, setup=setup)
        )
        result = performance_service.get_setup(db_session, response.id)

        assert [(item.id, item.quantity) for item in result.choirjobs] == [
            (choirjob.id, 2)
        ]

    def test_rejects_unknown_propriumelement(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        propriumwork = _make_propriumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    proprium=[
                        PerformancePropriumEntryInput(
                            propriumelement_id=999999, propriumwork_id=propriumwork.id
                        )
                    ],
                ),
            )

        assert exc_info.value.errors == [("proprium", "Element wurde nicht gefunden.")]

    def test_rejects_duplicate_propriumelement(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        element = _make_propriumelement(db_session)
        propriumwork_a = _make_propriumwork(db_session, composer_id)
        propriumwork_b = _make_propriumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    proprium=[
                        PerformancePropriumEntryInput(
                            propriumelement_id=element.id,
                            propriumwork_id=propriumwork_a.id,
                        ),
                        PerformancePropriumEntryInput(
                            propriumelement_id=element.id,
                            propriumwork_id=propriumwork_b.id,
                        ),
                    ],
                ),
            )

        assert exc_info.value.errors == [
            ("proprium", "Doppelter Eintrag für dasselbe Element.")
        ]

    def test_persists_proprium_and_orders_by_propriumelement_order(
        self, db_session: Session
    ):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        first_element = _make_propriumelement(db_session)
        first_element.order = 5
        second_element = _make_propriumelement(db_session)
        second_element.order = 1
        db_session.commit()
        first_work = _make_propriumwork(db_session, composer_id)
        second_work = _make_propriumwork(db_session, composer_id, demanding=True)

        response = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                proprium=[
                    PerformancePropriumEntryInput(
                        propriumelement_id=first_element.id,
                        propriumwork_id=first_work.id,
                    ),
                    PerformancePropriumEntryInput(
                        propriumelement_id=second_element.id,
                        propriumwork_id=second_work.id,
                    ),
                ],
            ),
        )

        proprium = performance_service.get_proprium(db_session, response.id)
        assert [entry.propriumelement_id for entry in proprium] == [
            second_element.id,
            first_element.id,
        ]
        assert proprium[0].demanding is True

    def test_rejects_rehearsal_before_tomorrow(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    rehearsals=[
                        PerformanceRehearsalInput(schedule=local_now(), comment=None)
                    ],
                ),
            )

        assert exc_info.value.errors == [
            ("rehearsals", "Proben-Datum muss frühestens morgen sein.")
        ]

    def test_rejects_rehearsal_after_performance(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    schedule=schedule,
                    rehearsals=[
                        PerformanceRehearsalInput(
                            schedule=schedule + timedelta(days=1), comment=None
                        )
                    ],
                ),
            )

        assert exc_info.value.errors == [
            ("rehearsals", "Proben-Datum muss vor Aufführungs-Datum liegen.")
        ]

    def test_persists_rehearsals_deduplicated_by_schedule(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        rehearsal_schedule = schedule - timedelta(days=1)

        response = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                rehearsals=[
                    PerformanceRehearsalInput(
                        schedule=rehearsal_schedule, comment="Erste"
                    ),
                    PerformanceRehearsalInput(
                        schedule=rehearsal_schedule, comment="Zweite"
                    ),
                ],
            ),
        )

        rehearsals = performance_service.get_rehearsals(db_session, response.id)
        assert len(rehearsals) == 1

    def test_rejects_same_location_and_hour(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        first_conductor = _make_artist(db_session, conductor=True)
        second_conductor = _make_artist(db_session, conductor=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        performance_service.create_performance(
            db_session,
            _request(
                location.id, work.id, schedule=schedule, artist_id=first_conductor
            ),
        )

        # Different conductors, so only the plain location+hour rule fires,
        # not the location+hour+conductor rule (isolates the two checks).
        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    schedule=schedule + timedelta(minutes=15),
                    artist_id=second_conductor,
                ),
            )

        assert exc_info.value.errors == [
            (
                "schedule",
                "Die Kombination aus Aufführungs-Stunde und Ort muss eindeutig sein.",
            )
        ]

    def test_rejects_same_location_hour_and_conductor(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        conductor_id = _make_artist(db_session, conductor=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        performance_service.create_performance(
            db_session,
            _request(location.id, work.id, schedule=schedule, artist_id=conductor_id),
        )
        other_location = _make_location(db_session)
        performance_service.create_performance(
            db_session,
            _request(
                other_location.id,
                work.id,
                schedule=schedule + timedelta(hours=3),
                artist_id=conductor_id,
            ),
        )

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.create_performance(
                db_session,
                _request(
                    location.id,
                    work.id,
                    schedule=schedule + timedelta(minutes=30),
                    artist_id=conductor_id,
                ),
            )

        assert (
            "schedule",
            performance_service._LOCATION_HOUR_ARTIST_COLLISION,
        ) in exc_info.value.errors

    def test_allows_same_location_and_hour_at_a_different_location(
        self, db_session: Session
    ):
        composer_id = _make_artist(db_session, composer=True)
        location_a = _make_location(db_session)
        location_b = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        performance_service.create_performance(
            db_session, _request(location_a.id, work.id, schedule=schedule)
        )

        response = performance_service.create_performance(
            db_session, _request(location_b.id, work.id, schedule=schedule)
        )

        assert response.location_id == location_b.id


class TestUpdatePerformance:
    def test_not_found_raises(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)

        with pytest.raises(performance_service.PerformanceNotFoundError):
            performance_service.update_performance(
                db_session, 999, _request(location.id, work.id)
            )

    def test_collision_check_also_runs_on_update(self, db_session: Session):
        """User-Entscheidung 2026-07-29: unlike Legacy (which only checked
        this on create), the collision check now also runs on update."""
        composer_id = _make_artist(db_session, composer=True)
        first_conductor = _make_artist(db_session, conductor=True)
        second_conductor = _make_artist(db_session, conductor=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        performance_service.create_performance(
            db_session,
            _request(
                location.id, work.id, schedule=schedule, artist_id=first_conductor
            ),
        )
        other = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule + timedelta(days=1),
                artist_id=second_conductor,
            ),
        )

        with pytest.raises(performance_service.PerformanceValidationError) as exc_info:
            performance_service.update_performance(
                db_session,
                other.id,
                _request(
                    location.id, work.id, schedule=schedule, artist_id=second_conductor
                ),
            )

        assert exc_info.value.errors == [
            (
                "schedule",
                "Die Kombination aus Aufführungs-Stunde und Ort muss eindeutig sein.",
            )
        ]

    def test_keeping_own_schedule_does_not_trigger_collision(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        schedule = _unique_schedule()
        created = performance_service.create_performance(
            db_session, _request(location.id, work.id, schedule=schedule)
        )

        updated = performance_service.update_performance(
            db_session,
            created.id,
            _request(location.id, work.id, schedule=schedule, description="neu"),
        )

        assert updated.description == "neu"

    def test_setup_sync_removes_updates_and_adds_positions(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        kept = _make_instrument(db_session)
        removed = _make_instrument(db_session)
        added = _make_voice(db_session)
        schedule = _unique_schedule()
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                setup=PerformanceSetupInput(
                    instruments=[
                        PerformancePositionInput(id=kept.id, quantity=1),
                        PerformancePositionInput(id=removed.id, quantity=1),
                    ]
                ),
            ),
        )

        performance_service.update_performance(
            db_session,
            created.id,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=kept.id, quantity=5)],
                    voices=[PerformancePositionInput(id=added.id, quantity=2)],
                ),
            ),
        )

        setup = performance_service.get_setup(db_session, created.id)
        assert [(item.id, item.quantity) for item in setup.instruments] == [
            (kept.id, 5)
        ]
        assert [(item.id, item.quantity) for item in setup.voices] == [(added.id, 2)]

    def test_setup_shrink_reconciles_bookings_via_booking_service(
        self, db_session: Session, make_user
    ):
        """Retrofit A.5b (see project_osa_migration_plan memory, Schritt 6
        plan): shrinking a position's quantity must demote the now-standby
        booking, and removing a position entirely must purge its bookings
        -- both via booking_service.reconcile_setup_change, wired in from
        update_performance()."""
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        kept_instrument = _make_instrument(db_session)
        removed_instrument = _make_instrument(db_session)
        schedule = _unique_schedule()
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                setup=PerformanceSetupInput(
                    instruments=[
                        PerformancePositionInput(id=kept_instrument.id, quantity=2),
                        PerformancePositionInput(id=removed_instrument.id, quantity=1),
                    ]
                ),
            ),
        )
        regular_user, standby_user = make_user(), make_user()
        removed_user = make_user()
        now = datetime.now(UTC)
        db_session.add_all(
            [
                Booking(
                    performance_id=created.id,
                    user_id=regular_user.id,
                    position_type="instruments",
                    position_id=kept_instrument.id,
                    fee=80,
                    order=0,
                    created_at=now,
                    updated_at=now,
                ),
                Booking(
                    performance_id=created.id,
                    user_id=standby_user.id,
                    position_type="instruments",
                    position_id=kept_instrument.id,
                    fee=80,
                    order=1,
                    created_at=now,
                    updated_at=now,
                ),
                Booking(
                    performance_id=created.id,
                    user_id=removed_user.id,
                    position_type="instruments",
                    position_id=removed_instrument.id,
                    fee=80,
                    order=0,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db_session.commit()

        performance_service.update_performance(
            db_session,
            created.id,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                setup=PerformanceSetupInput(
                    instruments=[
                        PerformancePositionInput(id=kept_instrument.id, quantity=1)
                    ]
                ),
            ),
        )

        # Shrinking a quantity does NOT remove the now-standby booking row
        # (its "regular"/"standby" status is derived from order < quantity,
        # not stored) -- only the REMOVED position's booking is actually
        # purged. This mirrors Legacy exactly: saveCastItem's demote path
        # only logs the transition, it never deletes on its own.
        remaining = (
            db_session.execute(
                select(Booking).where(Booking.performance_id == created.id)
            )
            .scalars()
            .all()
        )
        assert {b.user_id for b in remaining} == {regular_user.id, standby_user.id}

        logs = (
            db_session.execute(
                select(BookingLog)
                .where(BookingLog.performance_id == created.id)
                .order_by(BookingLog.id)
            )
            .scalars()
            .all()
        )
        assert any(
            log.user_id == standby_user.id and log.booking_type == "unbook"
            for log in logs
        )
        assert any(
            log.user_id == removed_user.id and log.booking_type == "unbook"
            for log in logs
        )

    def test_proprium_sync_removes_updates_and_adds_entries(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        kept_element = _make_propriumelement(db_session)
        removed_element = _make_propriumelement(db_session)
        added_element = _make_propriumelement(db_session)
        old_work_for_kept = _make_propriumwork(db_session, composer_id)
        new_work_for_kept = _make_propriumwork(db_session, composer_id)
        removed_work = _make_propriumwork(db_session, composer_id)
        added_work = _make_propriumwork(db_session, composer_id)
        schedule = _unique_schedule()
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                proprium=[
                    PerformancePropriumEntryInput(
                        propriumelement_id=kept_element.id,
                        propriumwork_id=old_work_for_kept.id,
                    ),
                    PerformancePropriumEntryInput(
                        propriumelement_id=removed_element.id,
                        propriumwork_id=removed_work.id,
                    ),
                ],
            ),
        )

        performance_service.update_performance(
            db_session,
            created.id,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                proprium=[
                    PerformancePropriumEntryInput(
                        propriumelement_id=kept_element.id,
                        propriumwork_id=new_work_for_kept.id,
                    ),
                    PerformancePropriumEntryInput(
                        propriumelement_id=added_element.id,
                        propriumwork_id=added_work.id,
                    ),
                ],
            ),
        )

        proprium = performance_service.get_proprium(db_session, created.id)
        by_element = {
            entry.propriumelement_id: entry.propriumwork_id for entry in proprium
        }
        assert by_element == {
            kept_element.id: new_work_for_kept.id,
            added_element.id: added_work.id,
        }

    def test_past_performance_cannot_be_updated(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        created = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )
        _move_to_past(db_session, created.id)

        with pytest.raises(performance_service.PerformanceInPastError):
            performance_service.update_performance(
                db_session, created.id, _request(location.id, work.id)
            )


class TestDeletePerformance:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(performance_service.PerformanceNotFoundError):
            performance_service.delete_performance(db_session, 999)

    def test_deletes_performance_and_its_positions_proprium_rehearsals(
        self, db_session: Session
    ):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        instrument = _make_instrument(db_session)
        schedule = _unique_schedule()
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                schedule=schedule,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
                ),
                rehearsals=[
                    PerformanceRehearsalInput(
                        schedule=schedule - timedelta(days=1), comment=None
                    )
                ],
            ),
        )

        performance_service.delete_performance(db_session, created.id)

        with pytest.raises(performance_service.PerformanceNotFoundError):
            performance_service.get_performance_detail(db_session, created.id)

    def test_past_performance_cannot_be_deleted(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        created = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )
        _move_to_past(db_session, created.id)

        with pytest.raises(performance_service.PerformanceInPastError):
            performance_service.delete_performance(db_session, created.id)

    def test_blocked_when_booking_exists(self, db_session: Session, make_user):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        instrument = _make_instrument(db_session)
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
                ),
            ),
        )
        user = make_user()
        now = datetime.now(UTC)
        db_session.add(
            Booking(
                performance_id=created.id,
                user_id=user.id,
                position_type="instruments",
                position_id=instrument.id,
                fee=80,
                order=0,
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        with pytest.raises(performance_service.PerformanceInUseError):
            performance_service.delete_performance(db_session, created.id)

    def test_blocked_when_booking_request_exists(self, db_session: Session, make_user):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        created = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )
        user = make_user()
        now = datetime.now(UTC)
        db_session.add(
            BookingRequest(
                performance_id=created.id,
                user_id=user.id,
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        with pytest.raises(performance_service.PerformanceInUseError):
            performance_service.delete_performance(db_session, created.id)


class TestGetFormData:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(performance_service.PerformanceNotFoundError):
            performance_service.get_form_data(db_session, 999)

    def test_deletable_is_false_when_booking_exists(
        self, db_session: Session, make_user
    ):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        instrument = _make_instrument(db_session)
        created = performance_service.create_performance(
            db_session,
            _request(
                location.id,
                work.id,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
                ),
            ),
        )
        user = make_user()
        now = datetime.now(UTC)
        db_session.add(
            Booking(
                performance_id=created.id,
                user_id=user.id,
                position_type="instruments",
                position_id=instrument.id,
                fee=80,
                order=0,
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        form_data = performance_service.get_form_data(db_session, created.id)

        assert form_data.deletable is False

    def test_past_performance_raises_immediately(self, db_session: Session):
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        created = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )
        _move_to_past(db_session, created.id)

        with pytest.raises(performance_service.PerformanceInPastError):
            performance_service.get_form_data(db_session, created.id)

    def test_returns_ordinariumwork_label_with_composer(self, db_session: Session):
        composer = artist_service.create_artist(
            db_session,
            ArtistRequest(surname="Bruckner", givenname="Anton", composer=True),
        )
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer.id)

        created = performance_service.create_performance(
            db_session, _request(location.id, work.id)
        )
        form_data = performance_service.get_form_data(db_session, created.id)

        assert form_data.ordinariumwork_label == f"BRUCKNER, Anton: {work.name}"
        assert form_data.deletable is True


class TestGetAvailableData:
    def test_conductors_excludes_composer_only_artists(self, db_session: Session):
        conductor_id = _make_artist(db_session, conductor=True)
        composer_only_id = _make_artist(db_session, composer=True)

        result = performance_service.get_available_data(db_session)

        conductor_ids = [item.id for item in result.conductors]
        assert conductor_id in conductor_ids
        assert composer_only_id not in conductor_ids

    def test_excludes_archived_instruments_voices_and_choirjobs(
        self, db_session: Session
    ):
        archived_instrument = _make_instrument(db_session)
        archived_instrument.active = False
        archived_voice = _make_voice(db_session)
        archived_voice.active = False
        archived_choirjob = _make_choirjob(db_session)
        archived_choirjob.active = False
        db_session.commit()

        result = performance_service.get_available_data(db_session)

        assert archived_instrument.id not in [item.id for item in result.instruments]
        assert archived_voice.id not in [item.id for item in result.voices]
        assert archived_choirjob.id not in [item.id for item in result.choirjobs]


class TestGetSetupActiveFlag:
    def test_archived_instrument_still_resolves_with_active_false(
        self, db_session: Session
    ):
        """An already-configured setup position must keep resolving
        correctly even after its Instrument gets archived -- get_setup()
        looks up by id regardless of active status (unlike
        get_available_data() above), only the `active` flag on the output
        itself reflects the archived state."""
        composer_id = _make_artist(db_session, composer=True)
        location = _make_location(db_session)
        work = _make_ordinariumwork(db_session, composer_id)
        instrument = _make_instrument(db_session)
        setup = PerformanceSetupInput(
            instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
        )
        response = performance_service.create_performance(
            db_session, _request(location.id, work.id, setup=setup)
        )
        instrument.active = False
        db_session.commit()

        result = performance_service.get_setup(db_session, response.id)

        position = next(item for item in result.instruments if item.id == instrument.id)
        assert position.active is False
