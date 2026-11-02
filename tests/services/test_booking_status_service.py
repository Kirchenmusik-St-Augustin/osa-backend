from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.services import booking_status_service, cast_service, performance_service
from tests.booking_helpers import (
    create_booking,
    create_booking_request,
    create_instrument,
    create_performance,
    get_performance,
    move_to_past,
    qualify,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestUserBookingStatus:
    def test_status_0_when_not_qualified_for_any_needed_position(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 0

    def test_status_0_for_past_performance_regardless_of_qualification(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        move_to_past(db_session, performance_id)
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 0

    def test_keep_past_status_reveals_real_status_for_past_performance(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        move_to_past(db_session, performance_id)
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id, keep_past_status=True
        )

        assert status.status == 1

    def test_status_1_when_qualified_and_unrequested(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 1

    def test_status_2_when_requested(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking_request(db_session, performance_id, user.id)
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 2

    def test_status_5_when_request_marked_notbooked(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking_request(
            db_session, performance_id, user.id, notbooked_at=datetime.now(UTC)
        )
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 5

    def test_status_4_when_booked_within_quantity(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 4
        assert status.position is not None
        assert status.position.id == instrument.id

    def test_status_3_when_booked_beyond_quantity(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=1
        )
        performance = get_performance(db_session, performance_id)

        status = booking_status_service.user_booking_status(
            db_session, performance, user.id
        )

        assert status.status == 3


class TestUserBookingStatusForPerformances:
    """The other axis of user_booking_status_batch(): one user, many
    performances -- what the calendar list needs."""

    def test_empty_performance_list_returns_empty_dict(
        self, db_session: Session, make_user
    ):
        user = make_user()

        result = booking_status_service.user_booking_status_for_performances(
            db_session, [], user.id
        )

        assert result == {}

    def test_batches_the_full_state_range_across_performances(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)

        not_bookable_id = create_performance(db_session)
        unrequested_id = create_performance(db_session, instruments={instrument.id: 1})
        booked_id = create_performance(db_session, instruments={instrument.id: 1})
        create_booking(
            db_session, booked_id, user.id, "instruments", instrument.id, order=0
        )
        past_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, past_id)

        performances = [
            get_performance(db_session, pid)
            for pid in (not_bookable_id, unrequested_id, booked_id, past_id)
        ]

        result = booking_status_service.user_booking_status_for_performances(
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
        instrument = create_instrument(db_session)
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)

        small_ids = [create_performance(db_session, instruments={instrument.id: 1})]
        large_ids = [
            create_performance(db_session, instruments={instrument.id: 1})
            for _ in range(5)
        ]

        # A single batched re-fetch per group (mirroring how the real
        # caller, list_performances_for_month(), loads its month's rows in
        # one query) -- fetching one-by-one here would interleave with each
        # create_performance()'s own commit() and expire the earlier objects
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
        # was expired by the create_performance() commits above (SQLAlchemy's
        # default expire_on_commit=True), so the FIRST post-expiry access to
        # `user.id` issues its own refresh SELECT -- counting that would
        # blame the function under test for a test-setup artifact.
        user_id = user.id

        with count_queries() as small_count:
            booking_status_service.user_booking_status_for_performances(
                db_session, list(small), user_id
            )

        with count_queries() as large_count:
            booking_status_service.user_booking_status_for_performances(
                db_session, list(large), user_id
            )

        assert large_count.count == small_count.count


class TestCancelAuthUserBooking:
    def test_promotes_next_standby_when_regular_cancels(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        regular, standby = make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(regular.id, 80), (standby.id, 80)],
            old_quantity=None,
        )

        booking_status_service.cancel_auth_user_booking(
            db_session, performance_id, regular.id
        )

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
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()

        booking_status_service.cancel_auth_user_booking(
            db_session, performance_id, user.id
        )

        assert (
            db_session.execute(
                select(BookingLog.id).where(BookingLog.user_id == user.id)
            ).first()
            is None
        )


class TestChangeUserRequestStatus:
    def test_status_1_creates_booking_request(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)

        status, notification = booking_status_service.change_user_request_status(
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
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking_request(db_session, performance_id, user.id)

        status, notification = booking_status_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 1
        assert notification is None

    def test_status_4_cancel_builds_notification_with_old_status(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user(roles=["disponent"])
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )

        status, notification = booking_status_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 1
        assert notification is not None
        assert notification.entry.previous_status == 4
        assert user.email in notification.disponent_emails

    def test_status_0_is_a_silent_noop(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()  # not qualified for anything

        status, notification = booking_status_service.change_user_request_status(
            db_session, performance_id, user
        )

        assert status.status == 0
        assert notification is None

    def test_double_request_raises(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking_request(
            db_session, performance_id, user.id, notbooked_at=datetime.now(UTC)
        )
        # status 5 dispatches to cancel, not request -- force the duplicate
        # path directly to exercise the defensive guard.
        with pytest.raises(booking_status_service.BookingRequestAlreadyExistsError):
            booking_status_service._request_booking(db_session, performance_id, user.id)

    def test_raises_for_past_performance(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        user = make_user()

        with pytest.raises(performance_service.PerformanceInPastError):
            booking_status_service.change_user_request_status(
                db_session, performance_id, user
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
        monkeypatch.setattr(booking_status_service, "_disponent_emails", lambda _db: [])
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        qualify(db_session, user.id, "instruments", instrument.id)
        create_booking(
            db_session, performance_id, user.id, "instruments", instrument.id, order=0
        )

        with patch("app.core.mailer._send_message") as mock_send:
            _, notification = booking_status_service.change_user_request_status(
                db_session, performance_id, user
            )

        assert notification is None
        mock_send.assert_not_called()
