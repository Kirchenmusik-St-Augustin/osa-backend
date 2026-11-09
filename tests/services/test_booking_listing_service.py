from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from app.core.datetime_utils import local_now
from app.schemas.pagination import MAX_PAGE_SIZE, PageParams
from app.services import booking_listing_service, cast_service, performance_service
from tests.booking_helpers import (
    create_booking,
    create_booking_request,
    create_instrument,
    create_performance,
    move_to_past,
    qualify,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.schemas.booking import PerformanceShortOutput


_ALL_ROWS = PageParams(limit=MAX_PAGE_SIZE, offset=0)


def _upcoming_requests_and_bookings(
    db: Session, user_id: uuid.UUID, *, upcoming_only: bool = True
) -> list[PerformanceShortOutput]:
    return list(
        booking_listing_service.get_upcoming_requests_and_bookings_for_user(
            db, user_id, _ALL_ROWS, upcoming_only=upcoming_only
        ).rows
    )


class TestGetRequestsAndBookings:
    def test_booked_users_listed_before_requesting_only_users_without_duplicates(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        booked = make_user()
        requesting = make_user()
        qualify(db_session, booked.id, "instruments", instrument.id)
        qualify(db_session, requesting.id, "instruments", instrument.id)
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(booked.id, 80)],
            old_quantity=None,
        )
        create_booking_request(db_session, performance_id, requesting.id)
        current_user = make_user()

        result = booking_listing_service.get_requests_and_bookings(
            db_session, performance_id, current_user
        )

        assert [entry.id for entry in result.entries] == [booked.id, requesting.id]

    def test_raises_for_past_performance(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        current_user = make_user()

        with pytest.raises(performance_service.PerformanceInPastError):
            booking_listing_service.get_requests_and_bookings(
                db_session, performance_id, current_user
            )


class TestGetUpcomingRequestsAndBookingsForUser:
    """The self-service "Meine Anfragen und Buchungen" page and the
    admin-side per-user requests-and-bookings view are both backed by this
    one generic, user_id-scoped function."""

    def test_includes_a_performance_with_a_booking(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert [item.id for item in result] == [performance_id]

    def test_includes_a_performance_with_only_an_open_request(
        self, db_session: Session, make_user
    ):
        performance_id = create_performance(db_session)
        user = make_user()
        create_booking_request(db_session, performance_id, user.id)

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert [item.id for item in result] == [performance_id]

    def test_includes_a_rejected_request_too_no_notbooked_filter(
        self, db_session: Session, make_user
    ):
        # There is no filter on notbooked_at at all.
        performance_id = create_performance(db_session)
        user = make_user()
        create_booking_request(
            db_session, performance_id, user.id, notbooked_at=datetime.now(UTC)
        )

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert [item.id for item in result] == [performance_id]

    def test_does_not_duplicate_a_performance_with_both_booking_and_request(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )
        create_booking_request(db_session, performance_id, user.id)

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert [item.id for item in result] == [performance_id]

    def test_excludes_past_performances(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        user = make_user()
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert result == []

    def test_upcoming_only_false_includes_past_performances(
        self, db_session: Session, make_user
    ):
        # The admin-side per-user view passes upcoming_only=False, unlike
        # the Selfadmin caller.
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        user = make_user()
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )

        result = _upcoming_requests_and_bookings(
            db_session, user.id, upcoming_only=False
        )

        assert [item.id for item in result] == [performance_id]

    def test_excludes_other_users_bookings(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        owner = make_user()
        other = make_user()
        create_booking(
            db_session, performance_id, owner.id, "instruments", instrument.id
        )

        result = _upcoming_requests_and_bookings(db_session, other.id)

        assert result == []

    def test_sorted_by_schedule(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        user = make_user()
        later_id = create_performance(
            db_session,
            instruments={instrument.id: 1},
            schedule=local_now() + timedelta(days=20),
        )
        earlier_id = create_performance(
            db_session,
            instruments={instrument.id: 1},
            schedule=local_now() + timedelta(days=5),
        )
        create_booking(db_session, later_id, user.id, "instruments", instrument.id)
        create_booking(db_session, earlier_id, user.id, "instruments", instrument.id)

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert [item.id for item in result] == [earlier_id, later_id]

    def test_pages_the_sorted_result_and_counts_every_row(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        user = make_user()
        performance_ids = [
            create_performance(
                db_session,
                instruments={instrument.id: 1},
                schedule=local_now() + timedelta(days=day),
            )
            for day in (3, 6, 9)
        ]
        for performance_id in reversed(performance_ids):
            create_booking(
                db_session, performance_id, user.id, "instruments", instrument.id
            )

        first = booking_listing_service.get_upcoming_requests_and_bookings_for_user(
            db_session, user.id, PageParams(limit=2, offset=0)
        )
        second = booking_listing_service.get_upcoming_requests_and_bookings_for_user(
            db_session, user.id, PageParams(limit=2, offset=2)
        )

        assert [item.id for item in first.rows] == performance_ids[:2]
        assert [item.id for item in second.rows] == performance_ids[2:]
        assert first.total == second.total == 3

    def test_a_user_without_any_row_has_an_empty_page_and_a_zero_total(
        self, db_session: Session, make_user
    ):
        result = booking_listing_service.get_upcoming_requests_and_bookings_for_user(
            db_session, make_user().id, _ALL_ROWS
        )

        assert (list(result.rows), result.total) == ([], 0)

    def test_reflects_the_real_bookable_badge_status_when_qualified(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id
        )

        result = _upcoming_requests_and_bookings(db_session, user.id)

        assert result[0].user_booking.status in (3, 4)

    def test_query_count_does_not_scale_with_result_count(
        self, db_session: Session, make_user, count_queries
    ):
        instrument = create_instrument(db_session)
        user = make_user()
        create_booking(
            db_session,
            create_performance(db_session, instruments={instrument.id: 1}),
            user.id,
            "instruments",
            instrument.id,
        )
        with count_queries() as small:
            small_result = _upcoming_requests_and_bookings(db_session, user.id)

        for _ in range(4):
            create_booking(
                db_session,
                create_performance(db_session, instruments={instrument.id: 1}),
                user.id,
                "instruments",
                instrument.id,
            )
        with count_queries() as large:
            large_result = _upcoming_requests_and_bookings(db_session, user.id)

        assert len(large_result) > len(small_result)
        assert large.count == small.count
