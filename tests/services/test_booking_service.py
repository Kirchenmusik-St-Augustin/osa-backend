import itertools
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.core.security import get_password_hash
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.user import User
from app.db.models.voice import Voice
from app.schemas.artist import ArtistRequest
from app.schemas.booking import (
    CastMemberInput,
    CastSaveRequest,
    CastSectionInput,
    CastSetupItemInput,
    NotBookedEntryInput,
    SendMessageRequest,
)
from app.schemas.fee import FeeRequest
from app.schemas.ordinariumwork import (
    OrdinariumworkPositionInput,
    OrdinariumworkRequest,
    OrdinariumworkSetupInput,
)
from app.schemas.performance import (
    PerformancePositionInput,
    PerformanceRequest,
    PerformanceSetupInput,
)
from app.services import (
    artist_service,
    booking_service,
    fee_service,
    ordinariumwork_service,
    performance_service,
)
from app.services.user_position_service import create_user_position

_schedule_counter = itertools.count(2)
_id_counter = itertools.count(700_000)


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _unique_id() -> int:
    return next(_id_counter)


def _unique_schedule() -> datetime:
    days_ahead = next(_schedule_counter)
    base = local_now() + timedelta(days=days_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


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


def _make_performance(
    db_session: Session,
    *,
    instruments: dict[int, int] | None = None,
    voices: dict[int, int] | None = None,
    choirjobs: dict[int, int] | None = None,
    schedule: datetime | None = None,
    extracost_amount: int | None = None,
    extracost_description: str | None = None,
) -> int:
    composer = artist_service.create_artist(
        db_session,
        ArtistRequest(surname=_unique("Composer"), givenname="Given", composer=True),
    )
    location = _make_location(db_session)
    work = _make_ordinariumwork(db_session, composer.id)
    setup = PerformanceSetupInput(
        instruments=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (instruments or {}).items()
        ],
        voices=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (voices or {}).items()
        ],
        choirjobs=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (choirjobs or {}).items()
        ],
    )
    request = PerformanceRequest(
        schedule=schedule or _unique_schedule(),
        location_id=location.id,
        ordinariumwork_id=work.id,
        artist_id=None,
        description=None,
        choirjob_defaultfee=35,
        instrument_defaultfee=60,
        voice_defaultfee=110,
        extracost_amount=extracost_amount,
        extracost_description=extracost_description,
        setup=setup,
        proprium=[],
        rehearsals=[],
    )
    performance = performance_service.create_performance(db_session, request)
    return performance.id


def _get_performance(db_session: Session, performance_id: int) -> Performance:
    return db_session.execute(
        select(Performance).where(Performance.id == performance_id)
    ).scalar_one()


def _move_to_past(db_session: Session, performance_id: int) -> None:
    performance = _get_performance(db_session, performance_id)
    performance.schedule = local_now() - timedelta(days=1)
    db_session.commit()


def _make_booking(
    db_session: Session,
    performance_id: int,
    user_id: int,
    position_type: str,
    position_id: int,
    *,
    fee: int = 80,
    order: int = 0,
) -> Booking:
    now = datetime.now(UTC)
    booking = Booking(
        performance_id=performance_id,
        user_id=user_id,
        position_type=position_type,
        position_id=position_id,
        fee=fee,
        order=order,
        created_at=now,
        updated_at=now,
    )
    db_session.add(booking)
    db_session.commit()
    return booking


def _make_booking_request(
    db_session: Session,
    performance_id: int,
    user_id: int,
    *,
    notbooked_at: datetime | None = None,
) -> BookingRequest:
    now = datetime.now(UTC)
    request = BookingRequest(
        performance_id=performance_id,
        user_id=user_id,
        notbooked_at=notbooked_at,
        created_at=now,
        updated_at=now,
    )
    db_session.add(request)
    db_session.commit()
    return request


def _make_named_user(db_session: Session, *, surname: str, givenname: str) -> User:
    user = User(
        surname=surname,
        givenname=givenname,
        email=f"{_unique('user')}@example.test",
        auth_password=get_password_hash("correct-horse-battery-staple"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def _qualify(
    db_session: Session, user_id: int, position_type: str, position_id: int
) -> None:
    create_user_position(
        db_session,
        user_id=user_id,
        position_type=position_type,
        position_id=position_id,
    )


class TestUserBookingStatus:
    def test_status_0_when_not_qualified_for_any_needed_position(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 0

    def test_status_0_for_past_performance_regardless_of_qualification(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _move_to_past(db_session, performance_id)
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 0

    def test_keep_past_status_reveals_real_status_for_past_performance(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _move_to_past(db_session, performance_id)
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(
            db_session, performance, user.id, keep_past_status=True
        )

        assert status.status == 1

    def test_status_1_when_qualified_and_unrequested(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 1

    def test_status_2_when_requested(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking_request(db_session, performance_id, user.id)
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 2

    def test_status_5_when_request_marked_notbooked(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking_request(
            db_session, performance_id, user.id, notbooked_at=datetime.now(UTC)
        )
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 5

    def test_status_4_when_booked_within_quantity(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 4
        assert status.position is not None
        assert status.position.id == instrument.id

    def test_status_3_when_booked_beyond_quantity(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=1
        )
        performance = _get_performance(db_session, performance_id)

        status = booking_service.user_booking_status(db_session, performance, user.id)

        assert status.status == 3


class TestUserBookingStatusForPerformances:
    """The other axis of user_booking_status_batch(): one user, many
    performances -- what the calendar list needs (see
    project_osa_migration_plan memory, Schritt 6 plan B.4 correction)."""

    def test_empty_performance_list_returns_empty_dict(
        self, db_session: Session, make_user
    ):
        user = make_user()

        result = booking_service.user_booking_status_for_performances(
            db_session, [], user.id
        )

        assert result == {}

    def test_batches_the_full_state_range_across_performances(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)

        not_bookable_id = _make_performance(db_session)
        unrequested_id = _make_performance(db_session, instruments={instrument.id: 1})
        booked_id = _make_performance(db_session, instruments={instrument.id: 1})
        _make_booking(
            db_session, booked_id, user.id, "instruments", instrument.id, order=0
        )
        past_id = _make_performance(db_session, instruments={instrument.id: 1})
        _move_to_past(db_session, past_id)

        performances = [
            _get_performance(db_session, pid)
            for pid in (not_bookable_id, unrequested_id, booked_id, past_id)
        ]

        result = booking_service.user_booking_status_for_performances(
            db_session, performances, user.id
        )

        assert result[not_bookable_id].status == 0
        assert result[unrequested_id].status == 1
        assert result[booked_id].status == 4
        assert result[booked_id].position is not None
        assert result[booked_id].position.id == instrument.id
        assert result[past_id].status == 0

    def test_query_count_does_not_scale_with_performance_count(
        self, db_session: Session, make_user, count_queries
    ):
        instrument = _make_instrument(db_session)
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)

        small_ids = [_make_performance(db_session, instruments={instrument.id: 1})]
        large_ids = [
            _make_performance(db_session, instruments={instrument.id: 1})
            for _ in range(5)
        ]

        # A single batched re-fetch per group (mirroring how the real
        # caller, list_performances_for_month(), loads its month's rows in
        # one query) -- fetching one-by-one here would interleave with each
        # _make_performance()'s own commit() and expire the earlier objects
        # (SQLAlchemy's default expire_on_commit=True), making every later
        # `.schedule` access inside the function under test issue its own
        # refresh SELECT -- a test artifact, not a real N+1.
        small = (
            db_session.execute(select(Performance).where(Performance.id.in_(small_ids)))
            .scalars()
            .all()
        )
        large = (
            db_session.execute(select(Performance).where(Performance.id.in_(large_ids)))
            .scalars()
            .all()
        )

        # Resolve the plain id once, outside both measured blocks: `user`
        # was expired by the _make_performance() commits above (SQLAlchemy's
        # default expire_on_commit=True), so the FIRST post-expiry access to
        # `user.id` issues its own refresh SELECT -- counting that would
        # blame the function under test for a test-setup artifact.
        user_id = user.id

        with count_queries() as small_count:
            booking_service.user_booking_status_for_performances(
                db_session, list(small), user_id
            )

        with count_queries() as large_count:
            booking_service.user_booking_status_for_performances(
                db_session, list(large), user_id
            )

        assert large_count.count == small_count.count


class TestDiffCastTransitions:
    def test_new_entry_within_quantity_books(self):
        result = booking_service._diff_cast_transitions(
            [], [(1, 80)], quantity=1, old_quantity=None
        )
        assert result == [(1, "book", 80)]

    def test_new_entry_beyond_quantity_unbooks(self):
        result = booking_service._diff_cast_transitions(
            [], [(1, 80)], quantity=0, old_quantity=None
        )
        assert result == [(1, "unbook", 80)]

    def test_dropped_entry_unbooks(self):
        result = booking_service._diff_cast_transitions(
            [(1, 80)], [], quantity=1, old_quantity=None
        )
        assert result == [(1, "unbook", 80)]

    def test_unchanged_regular_entry_logs_nothing(self):
        result = booking_service._diff_cast_transitions(
            [(1, 80)], [(1, 80)], quantity=1, old_quantity=None
        )
        assert result == []

    def test_promote_standby_to_regular_logs_book(self):
        # was at index 1 (standby, quantity=1), now moved to index 0 (regular)
        result = booking_service._diff_cast_transitions(
            [(2, 80), (1, 80)], [(1, 80), (2, 80)], quantity=1, old_quantity=None
        )
        assert (1, "book", 80) in result
        assert (2, "unbook", 80) in result

    def test_demote_regular_to_standby_logs_unbook(self):
        result = booking_service._diff_cast_transitions(
            [(1, 80), (2, 80)], [(2, 80), (1, 80)], quantity=1, old_quantity=None
        )
        assert (1, "unbook", 80) in result
        assert (2, "book", 80) in result

    def test_old_quantity_override_used_instead_of_current_quantity(self):
        # both entries were regular under the OLD quantity (2, unchanged
        # order) -- the new quantity shrank to 1, so only the was_regular
        # REFERENCE changes; the second entry must now be demoted even
        # though neither its position nor the cast list itself changed.
        result = booking_service._diff_cast_transitions(
            [(1, 80), (2, 80)], [(1, 80), (2, 80)], quantity=1, old_quantity=2
        )
        assert (2, "unbook", 80) in result
        assert (1, "unbook", 80) not in result


class TestSaveCastItem:
    def test_recreates_bookings_with_order_as_array_index(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        first, second = make_user(), make_user()

        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(first.id, 80), (second.id, 90)],
            old_quantity=None,
        )

        bookings = (
            db_session.execute(
                select(Booking)
                .where(Booking.performance_id == performance_id)
                .order_by(Booking.order)
            )
            .scalars()
            .all()
        )
        assert [(b.user_id, b.order, b.fee) for b in bookings] == [
            (first.id, 0, 80),
            (second.id, 1, 90),
        ]

    def test_moving_user_to_new_position_clears_other_position_booking(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        voice = _make_voice(db_session)
        performance_id = _make_performance(
            db_session, instruments={instrument.id: 1}, voices={voice.id: 1}
        )
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        booking_service._save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(user.id, 100)],
            old_quantity=None,
        )

        bookings = (
            db_session.execute(
                select(Booking).where(
                    Booking.performance_id == performance_id, Booking.user_id == user.id
                )
            )
            .scalars()
            .all()
        )
        assert len(bookings) == 1
        assert bookings[0].position_type == "voices"

    def test_cast_none_purges_and_logs_unbook_for_each(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=None,
            old_quantity=None,
        )

        remaining = (
            db_session.execute(
                select(Booking).where(Booking.performance_id == performance_id)
            )
            .scalars()
            .all()
        )
        assert remaining == []
        logs = (
            db_session.execute(
                select(BookingLog).where(
                    BookingLog.performance_id == performance_id,
                    BookingLog.user_id == user.id,
                )
            )
            .scalars()
            .all()
        )
        assert [log.booking_type for log in logs] == ["book", "unbook"]


class TestCancelAuthUserBooking:
    def test_promotes_next_standby_when_regular_cancels(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        regular, standby = make_user(), make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(regular.id, 80), (standby.id, 80)],
            old_quantity=None,
        )

        booking_service.cancel_auth_user_booking(db_session, performance_id, regular.id)

        remaining = (
            db_session.execute(
                select(Booking)
                .where(Booking.performance_id == performance_id)
                .order_by(Booking.order)
            )
            .scalars()
            .all()
        )
        assert [b.user_id for b in remaining] == [standby.id]
        assert remaining[0].order == 0

    def test_noop_when_user_has_no_booking(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()

        booking_service.cancel_auth_user_booking(
            db_session, performance_id, user.id
        )  # no crash


class TestReconcileSetupChange:
    def test_removed_position_is_purged_and_logged(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        booking_service.reconcile_setup_change(
            db_session, performance_id, {("instruments", instrument.id)}, {}
        )

        remaining = (
            db_session.execute(
                select(Booking).where(Booking.performance_id == performance_id)
            )
            .scalars()
            .all()
        )
        assert remaining == []

    def test_shrunk_quantity_demotes_against_old_quantity(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        first, second = make_user(), make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(first.id, 80), (second.id, 80)],
            old_quantity=None,
        )

        booking_service.reconcile_setup_change(
            db_session, performance_id, set(), {("instruments", instrument.id): 2}
        )

        logs = (
            db_session.execute(
                select(BookingLog)
                .where(BookingLog.performance_id == performance_id)
                .order_by(BookingLog.id)
            )
            .scalars()
            .all()
        )
        # second was regular under old_quantity=2 (index 1 < 2), current
        # quantity shrank to 1 -- must now be demoted (logged 'unbook').
        demote_logs = [log for log in logs if log.user_id == second.id]
        assert any(log.booking_type == "unbook" for log in demote_logs)


class TestGetCastPageAndSaveCast:
    def test_get_cast_page_reflects_current_setup_and_fees(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 2})
        fee_service.create_fee(db_session, FeeRequest(name=_unique("Fee"), amount=80))

        page = booking_service.get_cast_page(db_session, performance_id)

        assert page.setup.instruments[0].id == instrument.id
        assert page.setup.instruments[0].quantity == 2
        assert len(page.fees) >= 1

    def test_get_cast_page_sorts_bookable_candidates_alphabetically(
        self, db_session: Session
    ):
        # Legacy sorts these implicitly via User's global
        # OrderBySurnameGivenname scope, not any explicit orderBy in
        # Performance::staff() itself -- qualified user ids come out of a
        # plain Python set on this side, so this is a real regression risk,
        # not just cosmetic (see project_osa_migration_plan memory).
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        zimmermann = _make_named_user(
            db_session, surname="ZIMMERMANN", givenname="Anna"
        )
        adler = _make_named_user(db_session, surname="ADLER", givenname="Bernd")
        mueller = _make_named_user(db_session, surname="MUELLER", givenname="Clara")
        for user in (zimmermann, adler, mueller):
            _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking_request(db_session, performance_id, mueller.id)

        page = booking_service.get_cast_page(db_session, performance_id)

        bookable = page.staff.instruments[0].bookable
        assert [candidate.name for candidate in bookable.other] == [
            "ADLER, Bernd",
            "ZIMMERMANN, Anna",
        ]
        assert [candidate.name for candidate in bookable.requesting] == [
            "MUELLER, Clara",
        ]

    def test_get_cast_page_raises_for_past_performance(self, db_session: Session):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        _move_to_past(db_session, performance_id)

        with pytest.raises(performance_service.PerformanceInPastError):
            booking_service.get_cast_page(db_session, performance_id)

    def test_save_cast_books_users_and_marks_notbooked(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        booked, rejected = make_user(), make_user()
        _make_booking_request(db_session, performance_id, rejected.id)

        result = booking_service.save_cast(
            db_session,
            performance_id,
            CastSaveRequest(
                cast=CastSectionInput(
                    instruments=[
                        CastSetupItemInput(
                            id=instrument.id,
                            cast=[CastMemberInput(id=booked.id, fee=80)],
                        )
                    ]
                ),
                not_booked=[],
            ),
        )
        assert result.cast.instruments[0].cast[0].id == booked.id

        # rejected user was never part of the submitted cast/not_booked
        # payload at all -- notbooked_at stays untouched (still NULL), only
        # an EXPLICITLY rejected id gets marked.
        rejected_request = db_session.execute(
            select(BookingRequest).where(
                BookingRequest.performance_id == performance_id,
                BookingRequest.user_id == rejected.id,
            )
        ).scalar_one()
        assert rejected_request.notbooked_at is None

    def test_save_cast_marks_explicit_notbooked_ids(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        rejected = make_user()
        _make_booking_request(db_session, performance_id, rejected.id)

        booking_service.save_cast(
            db_session,
            performance_id,
            CastSaveRequest(
                cast=CastSectionInput(
                    instruments=[CastSetupItemInput(id=instrument.id, cast=[])]
                ),
                not_booked=[NotBookedEntryInput(id=rejected.id)],
            ),
        )

        rejected_request = db_session.execute(
            select(BookingRequest).where(
                BookingRequest.performance_id == performance_id,
                BookingRequest.user_id == rejected.id,
            )
        ).scalar_one()
        assert rejected_request.notbooked_at is not None


class TestChangeUserRequestStatus:
    def test_status_1_creates_booking_request(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)

        status, notification = booking_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 2
        assert notification is None
        assert (
            db_session.execute(
                select(BookingRequest).where(
                    BookingRequest.performance_id == performance_id,
                    BookingRequest.user_id == user.id,
                )
            ).scalar_one_or_none()
            is not None
        )

    def test_status_2_cancels_request_without_mail(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking_request(db_session, performance_id, user.id)

        status, notification = booking_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 1
        assert notification is None

    def test_status_4_cancel_builds_notification_with_old_status(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user(roles=["disponent"])
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )

        status, notification = booking_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 1
        assert notification is not None
        assert notification.entry.previous_status == 4
        assert user.email in notification.disponent_emails

    def test_status_0_is_a_silent_noop(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()  # not qualified for anything

        status, notification = booking_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 0
        assert notification is None

    def test_double_request_raises(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking_request(
            db_session, performance_id, user.id, notbooked_at=datetime.now(UTC)
        )
        # status 5 dispatches to cancel, not request -- force the duplicate
        # path directly to exercise the defensive guard.
        with pytest.raises(booking_service.BookingRequestAlreadyExistsError):
            booking_service._request_booking(db_session, performance_id, user.id)

    def test_raises_for_past_performance(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        _move_to_past(db_session, performance_id)
        user = make_user()

        with pytest.raises(performance_service.PerformanceInPastError):
            booking_service.change_user_request_status(db_session, performance_id, user)


class TestGetBilling:
    def test_billing_sums_booked_and_unfilled_slots(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 2})
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )
        current_user = make_user()

        billing = booking_service.get_billing(db_session, performance_id, current_user)

        assert (
            billing.billing.instruments.items[0].sum == 80 + 60
        )  # booked + default fee slot
        assert billing.billing.instruments.count == 2

    @pytest.mark.parametrize(
        ("instrument_count", "expected_fee"),
        [(0, 0), (1, 30), (12, 30), (13, 55)],
    )
    def test_instruments_orgfee_thresholds(self, instrument_count, expected_fee):
        orgfee = booking_service._org_fee(instrument_count, 0)
        assert orgfee.instruments == expected_fee

    @pytest.mark.parametrize(("choirjob_count", "expected_fee"), [(0, 0), (1, 15)])
    def test_choirjobs_orgfee_thresholds(self, choirjob_count, expected_fee):
        orgfee = booking_service._org_fee(0, choirjob_count)
        assert orgfee.choirjobs == expected_fee

    def test_billing_has_no_past_lock(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        _move_to_past(db_session, performance_id)
        current_user = make_user()

        billing = booking_service.get_billing(
            db_session, performance_id, current_user
        )  # no raise

        assert billing.billing.sum >= 0


class TestGetRequestsAndBookings:
    def test_booked_users_listed_before_requesting_only_users_without_duplicates(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        booked = make_user()
        requesting = make_user()
        _qualify(db_session, booked.id, "instruments", instrument.id)
        _qualify(db_session, requesting.id, "instruments", instrument.id)
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(booked.id, 80)],
            old_quantity=None,
        )
        _make_booking_request(db_session, performance_id, requesting.id)
        current_user = make_user()

        result = booking_service.get_requests_and_bookings(
            db_session, performance_id, current_user
        )

        assert [entry.id for entry in result.entries] == [booked.id, requesting.id]

    def test_raises_for_past_performance(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        _move_to_past(db_session, performance_id)
        current_user = make_user()

        with pytest.raises(performance_service.PerformanceInPastError):
            booking_service.get_requests_and_bookings(
                db_session, performance_id, current_user
            )


class TestGetMessageToCastPage:
    def test_returns_booked_cast_and_own_status(self, db_session: Session, make_user):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        booked = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(booked.id, 80)],
            old_quantity=None,
        )
        current_user = make_user()

        page = booking_service.get_message_to_cast_page(
            db_session, performance_id, current_user
        )

        assert page.booked_cast.instruments[0].cast[0].id == booked.id
        assert page.user_booking.status == 0  # current_user has no qualification at all


class TestGetPopular:
    def test_frequent_and_recent_bookers_from_past_performances_of_same_work(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        composer = artist_service.create_artist(
            db_session,
            ArtistRequest(
                surname=_unique("Composer"), givenname="Given", composer=True
            ),
        )
        # popularBookings() iterates the ORDINARIUMWORK's own instrument/
        # voice setup (ordinariumwork_positions), NOT the performance's --
        # must be configured via ordinariumwork_service, not the bare ORM
        # row _make_ordinariumwork() creates.
        work_response = ordinariumwork_service.create_ordinariumwork(
            db_session,
            OrdinariumworkRequest(
                name=_unique("Werk"),
                description=None,
                artist_id=composer.id,
                duration=None,
                demanding=False,
                setup=OrdinariumworkSetupInput(
                    instruments=[
                        OrdinariumworkPositionInput(id=instrument.id, quantity=1)
                    ]
                ),
            ),
        )
        work_id = work_response.id
        location = _make_location(db_session)

        past_offset_days = itertools.count(2)

        def _make_past_performance_with_booking(user_id: int) -> None:
            request = PerformanceRequest(
                schedule=_unique_schedule(),
                location_id=location.id,
                ordinariumwork_id=work_id,
                artist_id=None,
                description=None,
                choirjob_defaultfee=35,
                instrument_defaultfee=60,
                voice_defaultfee=110,
                extracost_amount=None,
                extracost_description=None,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
                ),
                proprium=[],
                rehearsals=[],
            )
            performance_id = performance_service.create_performance(
                db_session, request
            ).id
            # Each performance gets its OWN distinct past schedule --
            # `performances` has a real UNIQUE(schedule, location_id) index
            # (see tests/fixtures/legacy_schema.sql), so reusing
            # local_now()-1day for all of them (like the shared
            # _move_to_past() helper does) would risk a collision here.
            performance = _get_performance(db_session, performance_id)
            performance.schedule = local_now() - timedelta(days=next(past_offset_days))
            db_session.commit()
            booking_service._save_cast_item(
                db_session,
                performance_id,
                "instruments",
                instrument.id,
                new_cast=[(user_id, 80)],
                old_quantity=None,
            )

        frequent_user, occasional_user = make_user(), make_user()
        _make_past_performance_with_booking(frequent_user.id)
        _make_past_performance_with_booking(frequent_user.id)
        _make_past_performance_with_booking(frequent_user.id)
        _make_past_performance_with_booking(occasional_user.id)  # most recently created

        current_performance_id = performance_service.create_performance(
            db_session,
            PerformanceRequest(
                schedule=_unique_schedule(),
                location_id=location.id,
                ordinariumwork_id=work_id,
                artist_id=None,
                description=None,
                choirjob_defaultfee=35,
                instrument_defaultfee=60,
                voice_defaultfee=110,
                extracost_amount=None,
                extracost_description=None,
                setup=PerformanceSetupInput(
                    instruments=[PerformancePositionInput(id=instrument.id, quantity=1)]
                ),
                proprium=[],
                rehearsals=[],
            ),
        ).id

        page = booking_service.get_cast_page(db_session, current_performance_id)

        popular = page.popular.instruments[instrument.id]
        assert popular.frequent[0].id == frequent_user.id
        assert popular.frequent[0].total == 3
        assert popular.recent[0].id == occasional_user.id  # most recently updated


class TestMessageToCast:
    def test_get_message_recipients_type_all_collects_every_booked_user(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        recipients = booking_service.get_message_recipients(
            db_session, performance_id, None, None
        )

        assert [r.id for r in recipients] == [user.id]

    def test_get_message_recipients_for_specific_position(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        voice = _make_voice(db_session)
        performance_id = _make_performance(
            db_session, instruments={instrument.id: 1}, voices={voice.id: 1}
        )
        instrument_user, voice_user = make_user(), make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(instrument_user.id, 80)],
            old_quantity=None,
        )
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(voice_user.id, 100)],
            old_quantity=None,
        )

        recipients = booking_service.get_message_recipients(
            db_session, performance_id, "voices", voice.id
        )

        assert [r.id for r in recipients] == [voice_user.id]

    def test_get_message_recipients_distinguishes_has_email_from_verified_email(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        booking_service._save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        recipients = booking_service.get_message_recipients(
            db_session, performance_id, None, None
        )

        assert recipients[0].has_email is True
        assert recipients[0].email is None  # make_user() never verifies the email

    def test_send_message_to_cast_returns_verified_recipients_only(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        recipient = make_user()
        recipient.email_verified_at = datetime.now(UTC)
        db_session.commit()

        to_emails, sender_name, message = booking_service.send_message_to_cast(
            db_session,
            performance_id,
            sender,
            SendMessageRequest(recipient_ids=[recipient.id], message="Hallo!"),
        )

        assert to_emails == [recipient.email]
        assert sender_name == f"{sender.surname}, {sender.givenname}"
        assert message == "Hallo!"

    def test_send_message_to_cast_raises_when_no_recipient_is_verified(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        recipient = make_user()  # never verified

        with pytest.raises(booking_service.MessageRecipientsEmptyError):
            booking_service.send_message_to_cast(
                db_session,
                performance_id,
                sender,
                SendMessageRequest(recipient_ids=[recipient.id], message="Hallo!"),
            )


class TestSendBookedOrStandbyCanceledIntegration:
    def test_no_notification_built_when_no_disponent_exists(
        self, db_session: Session, make_user, monkeypatch: pytest.MonkeyPatch
    ):
        # The shared test-session DB (see conftest.py) has no per-test
        # rollback -- other tests in this module create real 'disponent'
        # users that a real _disponent_emails() query would still find
        # here. Monkeypatching it directly is the only reliable way to
        # exercise "genuinely zero disponent recipients".
        monkeypatch.setattr(booking_service, "_disponent_emails", lambda _db: [])
        instrument = _make_instrument(db_session)
        performance_id = _make_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        _qualify(db_session, user.id, "instruments", instrument.id)
        _make_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )

        with patch("app.core.mailer._send_message") as mock_send:
            _, notification = booking_service.change_user_request_status(
                db_session, performance_id, user
            )

        assert notification is None
        mock_send.assert_not_called()
