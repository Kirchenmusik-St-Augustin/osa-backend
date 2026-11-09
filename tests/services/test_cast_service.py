import itertools
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.core.datetime_utils import local_now
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.schemas.artist import ArtistRequest
from app.schemas.booking import (
    CastMemberInput,
    CastSaveRequest,
    CastSectionInput,
    CastSetupItemInput,
    NotBookedEntryInput,
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
    booking_status_service,
    cast_service,
    fee_service,
    ordinariumwork_service,
    performance_service,
)
from app.services.position_types import POSITION_TYPES, position_key
from tests.booking_helpers import (
    create_booking,
    create_booking_request,
    create_choirjob,
    create_instrument,
    create_location,
    create_named_user,
    create_performance,
    create_voice,
    get_performance,
    move_to_past,
    qualify,
    unique,
    unique_schedule,
)
from tests.sql_capture import recorded_statements

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.position_types import PositionType


class TestCastMemberInputSchema:
    def test_rejects_out_of_range_fee(self):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(le=999)
            CastMemberInput(id=uuid.uuid4(), fee=1000)


class TestDiffCastTransitions:
    def test_new_entry_within_quantity_books(self):
        result = cast_service._diff_cast_transitions(
            [], [(1, 80)], quantity=1, old_quantity=None
        )
        assert result == [(1, "book", 80)]

    def test_new_entry_beyond_quantity_unbooks(self):
        result = cast_service._diff_cast_transitions(
            [], [(1, 80)], quantity=0, old_quantity=None
        )
        assert result == [(1, "unbook", 80)]

    def test_dropped_entry_unbooks(self):
        result = cast_service._diff_cast_transitions(
            [(1, 80)], [], quantity=1, old_quantity=None
        )
        assert result == [(1, "unbook", 80)]

    def test_unchanged_regular_entry_logs_nothing(self):
        result = cast_service._diff_cast_transitions(
            [(1, 80)], [(1, 80)], quantity=1, old_quantity=None
        )
        assert result == []

    def test_promote_standby_to_regular_logs_book(self):
        # was at index 1 (standby, quantity=1), now moved to index 0 (regular)
        result = cast_service._diff_cast_transitions(
            [(2, 80), (1, 80)], [(1, 80), (2, 80)], quantity=1, old_quantity=None
        )
        assert (1, "book", 80) in result
        assert (2, "unbook", 80) in result

    def test_demote_regular_to_standby_logs_unbook(self):
        result = cast_service._diff_cast_transitions(
            [(1, 80), (2, 80)], [(2, 80), (1, 80)], quantity=1, old_quantity=None
        )
        assert (1, "unbook", 80) in result
        assert (2, "book", 80) in result

    def test_old_quantity_override_used_instead_of_current_quantity(self):
        # both entries were regular under the OLD quantity (2, unchanged
        # order) -- the new quantity shrank to 1, so only the was_regular
        # REFERENCE changes; the second entry must now be demoted even
        # though neither its position nor the cast list itself changed.
        result = cast_service._diff_cast_transitions(
            [(1, 80), (2, 80)], [(1, 80), (2, 80)], quantity=1, old_quantity=2
        )
        assert (2, "unbook", 80) in result
        assert (1, "unbook", 80) not in result


class TestSaveCastItem:
    def test_recreates_bookings_with_order_as_array_index(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        first, second = make_user(), make_user()

        cast_service.save_cast_item(
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
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        performance_id = create_performance(
            db_session, instruments={instrument.id: 1}, voices={voice.id: 1}
        )
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        cast_service.save_cast_item(
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
        assert bookings[0].voice_id == voice.id

    def test_cast_none_purges_and_logs_unbook_for_each(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        cast_service.save_cast_item(
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


def _delete_statements(statements: list[str]) -> list[str]:
    return [
        s for s in statements if s.lstrip().upper().startswith("DELETE FROM BOOKINGS")
    ]


class TestSaveCastItemStatements:
    @pytest.mark.parametrize("cast_size", [1, 3, 8])
    def test_clearing_other_positions_costs_one_delete_however_large_the_cast(
        self, db_session: Session, make_user, cast_size: int
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        users = [make_user() for _ in range(cast_size)]

        with recorded_statements() as statements:
            cast_service.save_cast_item(
                db_session,
                performance_id,
                "instruments",
                instrument.id,
                new_cast=[(user.id, 80) for user in users],
                old_quantity=None,
            )

        # One delete of the position's old rows, one for the members' rows
        # at other positions.
        assert len(_delete_statements(statements)) == 2

    def test_an_empty_cast_clears_no_other_position(self, db_session: Session):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})

        with recorded_statements() as statements:
            cast_service.save_cast_item(
                db_session,
                performance_id,
                "instruments",
                instrument.id,
                new_cast=[],
                old_quantity=None,
            )

        assert len(_delete_statements(statements)) == 1

    def test_several_members_moved_at_once_leave_one_booking_each(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        performance_id = create_performance(
            db_session, instruments={instrument.id: 2}, voices={voice.id: 2}
        )
        first, second = make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(first.id, 80), (second.id, 80)],
            old_quantity=None,
        )

        cast_service.save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(second.id, 100), (first.id, 100)],
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
        assert [(b.user_id, b.voice_id, b.instrument_id) for b in bookings] == [
            (second.id, voice.id, None),
            (first.id, voice.id, None),
        ]


def _performance_selects(statements: list[str]) -> list[str]:
    return [
        s
        for s in statements
        if s.lstrip().upper().startswith("SELECT") and "FROM performances " in s
    ]


class TestWritersLockThePerformance:
    def test_save_cast_locks_the_performance_row(self, db_session: Session):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})

        with recorded_statements() as statements:
            cast_service.save_cast(
                db_session,
                performance_id,
                CastSaveRequest(cast=CastSectionInput(), not_booked=[]),
            )

        assert "FOR UPDATE" in _performance_selects(statements)[0]

    def test_change_user_request_status_locks_the_performance_row(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)

        with recorded_statements() as statements:
            booking_status_service.change_user_request_status(
                db_session, performance_id, user
            )

        assert "FOR UPDATE" in _performance_selects(statements)[0]

    def test_reconcile_setup_change_locks_before_it_reads_any_booking(
        self, db_session: Session
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        removed_keys: set[tuple[PositionType, uuid.UUID]] = {
            ("instruments", instrument.id)
        }

        with recorded_statements() as statements:
            cast_service.reconcile_setup_change(
                db_session, performance_id, removed_keys, {}
            )

        first = statements[0]
        assert "FROM performances " in first
        assert "FOR UPDATE" in first

    def test_a_read_only_lookup_takes_no_lock(self, db_session: Session):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})

        with recorded_statements() as statements:
            cast_service.get_cast_page(db_session, performance_id)

        assert all("FOR UPDATE" not in s for s in statements)


class TestReconcileSetupChange:
    def test_removed_position_is_purged_and_logged(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        cast_service.reconcile_setup_change(
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
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        first, second = make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(first.id, 80), (second.id, 80)],
            old_quantity=None,
        )

        cast_service.reconcile_setup_change(
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
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 2})
        fee_service.create_fee(db_session, FeeRequest(name=unique("Fee"), amount=80))

        page = cast_service.get_cast_page(db_session, performance_id)

        assert page.setup.instruments[0].id == instrument.id
        assert page.setup.instruments[0].quantity == 2
        assert len(page.fees) >= 1

    def test_get_cast_page_sorts_bookable_candidates_alphabetically(
        self, db_session: Session
    ):
        # Qualified user ids come out of a plain Python set, so the
        # alphabetical order has to be enforced explicitly -- a real
        # regression risk, not just cosmetic.
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        zimmermann = create_named_user(
            db_session, surname="ZIMMERMANN", givenname="Anna"
        )
        adler = create_named_user(db_session, surname="ADLER", givenname="Bernd")
        mueller = create_named_user(db_session, surname="MUELLER", givenname="Clara")
        for user in (zimmermann, adler, mueller):
            qualify(db_session, user.id, "instruments", instrument.id)
        create_booking_request(db_session, performance_id, mueller.id)

        page = cast_service.get_cast_page(db_session, performance_id)

        bookable = page.staff.instruments[0].bookable
        assert [candidate.name for candidate in bookable.other] == [
            "ADLER, Bernd",
            "ZIMMERMANN, Anna",
        ]
        assert [candidate.name for candidate in bookable.requesting] == [
            "MUELLER, Clara",
        ]

    def test_get_cast_page_raises_for_past_performance(self, db_session: Session):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)

        with pytest.raises(performance_service.PerformanceInPastError):
            cast_service.get_cast_page(db_session, performance_id)

    def test_save_cast_books_users_and_marks_notbooked(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        booked, rejected = make_user(), make_user()
        create_booking_request(db_session, performance_id, rejected.id)

        result = cast_service.save_cast(
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
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        rejected = make_user()
        create_booking_request(db_session, performance_id, rejected.id)

        cast_service.save_cast(
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


class TestPrimaryVoiceByUser:
    def test_picks_lowest_order_voice_when_user_has_multiple(
        self, db_session: Session, make_user
    ):
        alt = create_voice(db_session, order=2)
        sopran = create_voice(db_session, order=1)
        user = make_user()
        # Qualified for both, deliberately in an order that does NOT match
        # canonical Voice.order, so the result can't be a coincidence of
        # insertion order.
        qualify(db_session, user.id, "voices", alt.id)
        qualify(db_session, user.id, "voices", sopran.id)

        result = cast_service._primary_voice_by_user(db_session, {user.id})

        assert result[user.id].id == sopran.id
        assert result[user.id].name == sopran.name

    def test_user_with_no_voice_assignment_is_absent_from_result(
        self, db_session: Session, make_user
    ):
        user = make_user()

        result = cast_service._primary_voice_by_user(db_session, {user.id})

        assert user.id not in result

    def test_empty_input_short_circuits_without_querying(
        self, db_session: Session, count_queries
    ):
        with count_queries() as counter:
            result = cast_service._primary_voice_by_user(db_session, set())

        assert result == {}
        assert counter.count == 0

    def test_query_count_does_not_scale_with_user_count(
        self, db_session: Session, make_user, count_queries
    ):
        voice = create_voice(db_session)
        one_user = make_user()
        qualify(db_session, one_user.id, "voices", voice.id)
        small_ids = {one_user.id}
        with count_queries() as small:
            cast_service._primary_voice_by_user(db_session, small_ids)

        many_users = [make_user() for _ in range(5)]
        for user in many_users:
            qualify(db_session, user.id, "voices", voice.id)
        # Collect ids BEFORE entering the counted block -- `user.id` access
        # on an expired ORM instance (every object gets expired by each
        # `qualify()` call's internal commit, default expire_on_commit)
        # triggers its own refresh SELECT, which would otherwise inflate
        # the count with something that has nothing to do with the
        # function under test.
        large_ids = {user.id for user in many_users}
        with count_queries() as large:
            cast_service._primary_voice_by_user(db_session, large_ids)

        assert small.count == large.count == 2


class TestChoirjobVoiceEnrichment:
    def test_booked_choirjob_member_carries_their_primary_voice(
        self, db_session: Session, make_user
    ):
        choirjob = create_choirjob(db_session)
        voice = create_voice(db_session, order=3)
        performance_id = create_performance(db_session, choirjobs={choirjob.id: 1})
        user = make_user()
        qualify(db_session, user.id, "voices", voice.id)
        create_booking(db_session, performance_id, user.id, "choirjobs", choirjob.id)

        page = cast_service.get_cast_page(db_session, performance_id)

        member = page.form_data.cast.choirjobs[0].cast[0]
        assert member.voice_name == voice.name
        assert member.voice_order == voice.order

    def test_instrument_cast_member_never_carries_voice_fields(
        self, db_session: Session, make_user
    ):
        # User IS qualified for a Voice, but is booked as an INSTRUMENT --
        # regression guard against accidentally enriching all three
        # sections instead of only choirjobs.
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "voices", voice.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )

        page = cast_service.get_cast_page(db_session, performance_id)

        member = page.form_data.cast.instruments[0].cast[0]
        assert member.voice_name is None
        assert member.voice_order is None

    def test_choirjob_staff_candidate_carries_their_primary_voice(
        self, db_session: Session, make_user
    ):
        choirjob = create_choirjob(db_session)
        voice = create_voice(db_session, order=4)
        performance_id = create_performance(db_session, choirjobs={choirjob.id: 1})
        candidate = make_user()
        qualify(db_session, candidate.id, "voices", voice.id)
        qualify(db_session, candidate.id, "choirjobs", choirjob.id)

        page = cast_service.get_cast_page(db_session, performance_id)

        bookable = page.staff.choirjobs[0].bookable
        assert bookable.other[0].voice_name == voice.name
        assert bookable.other[0].voice_order == voice.order

    def test_choirjob_member_with_no_voice_assignment_has_none_fields(
        self, db_session: Session, make_user
    ):
        choirjob = create_choirjob(db_session)
        performance_id = create_performance(db_session, choirjobs={choirjob.id: 1})
        user = make_user()
        create_booking(db_session, performance_id, user.id, "choirjobs", choirjob.id)

        page = cast_service.get_cast_page(db_session, performance_id)

        member = page.form_data.cast.choirjobs[0].cast[0]
        assert member.voice_name is None
        assert member.voice_order is None


class TestGetPopular:
    def test_frequent_and_recent_bookers_from_past_performances_of_same_work(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        composer = artist_service.create_artist(
            db_session,
            ArtistRequest(surname=unique("Composer"), givenname="Given", composer=True),
        )
        # popularBookings() iterates the ORDINARIUMWORK's own instrument/
        # voice setup (ordinariumwork_positions), NOT the performance's --
        # must be configured via ordinariumwork_service, not the bare ORM
        # row create_ordinariumwork() creates.
        work_response = ordinariumwork_service.create_ordinariumwork(
            db_session,
            OrdinariumworkRequest(
                name=unique("Werk"),
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
        location = create_location(db_session)

        past_offset_days = itertools.count(2)

        def _make_past_performance_with_booking(user_id: int) -> None:
            request = PerformanceRequest(
                schedule=unique_schedule(),
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
            # `performances` has a real UNIQUE(schedule, location_id) index,
            # so reusing local_now()-1day for all of them (like the shared
            # move_to_past() helper does) would risk a collision here.
            performance = get_performance(db_session, performance_id)
            performance.schedule = local_now() - timedelta(days=next(past_offset_days))
            db_session.commit()
            cast_service.save_cast_item(
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
                schedule=unique_schedule(),
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

        page = cast_service.get_cast_page(db_session, current_performance_id)

        popular = page.popular.instruments[instrument.id]
        assert popular.frequent[0].id == frequent_user.id
        assert popular.frequent[0].total == 3
        assert popular.recent[0].id == occasional_user.id  # most recently updated


_POSITION_MAKERS = {
    "instruments": create_instrument,
    "voices": create_voice,
    "choirjobs": create_choirjob,
}


def _two_positions_with_one_performance(
    db_session: Session, position_type: PositionType
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    first = _POSITION_MAKERS[position_type](db_session)
    second = _POSITION_MAKERS[position_type](db_session)
    performance_id = create_performance(
        db_session, **{position_type: {first.id: 1, second.id: 1}}
    )
    return performance_id, first.id, second.id


def _booked_positions(
    db_session: Session, performance_id: uuid.UUID
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    bookings = (
        db_session.execute(
            select(Booking).where(Booking.performance_id == performance_id)
        )
        .scalars()
        .all()
    )
    return {(booking.user_id, position_key(booking)[1]) for booking in bookings}


@pytest.mark.parametrize("position_type", POSITION_TYPES)
class TestEveryPositionType:
    """The cast of one position never touches the cast of another position of
    the same type, for instruments, voices and choirjobs alike."""

    def test_saving_a_cast_replaces_only_the_bookings_of_its_own_position(
        self, db_session: Session, make_user, position_type: PositionType
    ):
        performance_id, first_id, second_id = _two_positions_with_one_performance(
            db_session, position_type
        )
        first_user, second_user, third_user = make_user(), make_user(), make_user()
        for position_id, user in ((first_id, first_user), (second_id, second_user)):
            cast_service.save_cast_item(
                db_session,
                performance_id,
                position_type,
                position_id,
                new_cast=[(user.id, 80)],
                old_quantity=None,
            )

        cast_service.save_cast_item(
            db_session,
            performance_id,
            position_type,
            first_id,
            new_cast=[(third_user.id, 70)],
            old_quantity=None,
        )

        assert _booked_positions(db_session, performance_id) == {
            (third_user.id, first_id),
            (second_user.id, second_id),
        }

    def test_a_cancelled_regular_is_replaced_by_the_standby_of_the_same_position(
        self, db_session: Session, make_user, position_type: PositionType
    ):
        performance_id, first_id, second_id = _two_positions_with_one_performance(
            db_session, position_type
        )
        regular, standby, other = make_user(), make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            position_type,
            first_id,
            new_cast=[(regular.id, 80), (standby.id, 80)],
            old_quantity=None,
        )
        cast_service.save_cast_item(
            db_session,
            performance_id,
            position_type,
            second_id,
            new_cast=[(other.id, 90)],
            old_quantity=None,
        )

        booking_status_service.cancel_auth_user_booking(
            db_session, performance_id, regular.id
        )

        assert _booked_positions(db_session, performance_id) == {
            (standby.id, first_id),
            (other.id, second_id),
        }


@pytest.mark.parametrize("position_type", ["instruments", "voices"])
def test_popular_bookers_count_only_the_bookings_of_the_asked_position(
    db_session: Session, make_user, position_type: PositionType
):
    performance_id, first_id, second_id = _two_positions_with_one_performance(
        db_session, position_type
    )
    first_user, second_user = make_user(), make_user()
    for position_id, user in ((first_id, first_user), (second_id, second_user)):
        cast_service.save_cast_item(
            db_session,
            performance_id,
            position_type,
            position_id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

    popular = cast_service._popular_for_position(
        db_session, [performance_id], position_type, first_id
    )

    assert [entry.id for entry in popular.frequent] == [first_user.id]
    assert [entry.id for entry in popular.recent] == [first_user.id]
