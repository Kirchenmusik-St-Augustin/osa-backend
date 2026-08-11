import itertools
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.schemas.artist import ArtistRequest
from app.schemas.performance import PerformanceRequest, PerformanceSetupInput
from app.services import artist_service, booking_jobs, performance_service

_schedule_counter = itertools.count(2)


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


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


def _make_performance(db_session: Session, *, schedule: datetime | None = None) -> int:
    composer = artist_service.create_artist(
        db_session,
        ArtistRequest(surname=_unique("Composer"), givenname="Given", composer=True),
    )
    location = _make_location(db_session)
    work = _make_ordinariumwork(db_session, composer.id)
    performance = performance_service.create_performance(
        db_session,
        PerformanceRequest(
            schedule=schedule or _unique_schedule(),
            location_id=location.id,
            ordinariumwork_id=work.id,
            artist_id=None,
            description=None,
            choirjob_defaultfee=35,
            instrument_defaultfee=60,
            voice_defaultfee=110,
            extracost_amount=None,
            extracost_description=None,
            setup=PerformanceSetupInput(),
            proprium=[],
            rehearsals=[],
        ),
    )
    return performance.id


def _move_to_past(
    db_session: Session, performance_id: int, *, days_ago: int = 1
) -> int:
    performance = db_session.execute(
        select(Performance).where(Performance.id == performance_id)
    ).scalar_one()
    performance.schedule = local_now() - timedelta(days=days_ago)
    db_session.commit()
    return performance_id


def _make_booking_request(
    db_session: Session, performance_id: int, user_id: int
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        BookingRequest(
            performance_id=performance_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()


def _make_log(
    db_session: Session,
    *,
    performance_id: int,
    user_id: int,
    booking_type: str,
    notified_at: datetime | None = None,
    created_at: datetime | None = None,
) -> BookingLog:
    now = created_at or datetime.now(UTC)
    log = BookingLog(
        performance_id=performance_id,
        user_id=user_id,
        booking_type=booking_type,
        position_type="instruments",
        position_id=1,
        fee=80,
        notified_at=notified_at,
        created_at=now,
        updated_at=now,
    )
    db_session.add(log)
    db_session.commit()
    return log


class TestPurgeStaleBookingRequests:
    def test_deletes_requests_for_past_performances(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        _move_to_past(db_session, performance_id)
        user = make_user()
        _make_booking_request(db_session, performance_id, user.id)

        booking_jobs.purge_stale_booking_requests()

        remaining = (
            db_session.execute(
                select(BookingRequest).where(
                    BookingRequest.performance_id == performance_id
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []

    def test_keeps_requests_for_future_performances(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        _make_booking_request(db_session, performance_id, user.id)

        booking_jobs.purge_stale_booking_requests()

        remaining = (
            db_session.execute(
                select(BookingRequest).where(
                    BookingRequest.performance_id == performance_id
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 1


class TestLatestUnnotifiedEntries:
    def test_never_notified_book_is_notify_worthy(self, db_session: Session, make_user):
        performance_id = _make_performance(db_session)
        user = make_user()
        log = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
        )

        result = booking_jobs._latest_unnotified_entries([log])

        assert result[(performance_id, user.id)] is log

    def test_never_notified_unbook_is_not_notify_worthy(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        log = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="unbook",
        )

        result = booking_jobs._latest_unnotified_entries([log])

        assert (performance_id, user.id) not in result

    def test_already_notified_for_latest_state_is_skipped(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        log = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
            notified_at=datetime.now(UTC),
        )

        result = booking_jobs._latest_unnotified_entries([log])

        assert (performance_id, user.id) not in result

    def test_status_change_since_last_notification_is_notify_worthy(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        base = datetime.now(UTC)
        notified_book = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
            notified_at=base,
            created_at=base,
        )
        latest_unbook = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="unbook",
            created_at=base + timedelta(minutes=5),
        )

        result = booking_jobs._latest_unnotified_entries([notified_book, latest_unbook])

        assert result[(performance_id, user.id)] is latest_unbook

    def test_same_status_since_last_notification_is_not_notify_worthy(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        base = datetime.now(UTC)
        notified_book = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
            notified_at=base,
            created_at=base,
        )
        latest_book_again = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
            created_at=base + timedelta(minutes=5),
        )

        result = booking_jobs._latest_unnotified_entries(
            [notified_book, latest_book_again]
        )

        assert (performance_id, user.id) not in result

    def test_collects_separate_entries_across_multiple_performances_for_same_user(
        self, db_session: Session, make_user
    ):
        first_performance_id = _make_performance(db_session)
        second_performance_id = _make_performance(db_session)
        user = make_user()
        first_log = _make_log(
            db_session,
            performance_id=first_performance_id,
            user_id=user.id,
            booking_type="book",
        )
        second_log = _make_log(
            db_session,
            performance_id=second_performance_id,
            user_id=user.id,
            booking_type="book",
        )

        result = booking_jobs._latest_unnotified_entries([first_log, second_log])

        assert result[(first_performance_id, user.id)] is first_log
        assert result[(second_performance_id, user.id)] is second_log


class TestNotifyUpcomingBookingStatus:
    def test_sends_one_mail_per_user_and_marks_notified(
        self, db_session: Session, make_user
    ):
        performance_id = _make_performance(db_session)
        user = make_user()
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()
        log = _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
        )

        with patch("app.core.mailer._send_message") as mock_send:
            booking_jobs.notify_upcoming_booking_status()

        # Runs against the whole (shared, non-hermetic-across-tests) DB by
        # design -- assert this user's own call happened, not an exact
        # total call count, since other tests' leftover verified users
        # with pending notifications may legitimately coexist.
        matching_calls = [
            call for call in mock_send.call_args_list if call.args[1] == [user.email]
        ]
        assert len(matching_calls) == 1
        # notify_upcoming_booking_status() commits via its OWN SessionLocal()
        # -- db_session already has `log` in its identity map from creating
        # it above, so a plain re-query would return the stale cached
        # object without expire() forcing an actual re-SELECT.
        db_session.expire(log)
        assert log.notified_at is not None

    def test_skips_users_without_verified_email(self, db_session: Session, make_user):
        performance_id = _make_performance(db_session)
        user = make_user(verified=False)
        _make_log(
            db_session,
            performance_id=performance_id,
            user_id=user.id,
            booking_type="book",
        )

        with patch("app.core.mailer._send_message") as mock_send:
            booking_jobs.notify_upcoming_booking_status()

        assert all(call.args[1] != [user.email] for call in mock_send.call_args_list)

    def test_noop_when_no_upcoming_performances_have_logs(self, db_session: Session):
        # Doesn't create any data of its own -- only asserts this doesn't
        # crash against whatever (possibly empty, possibly not) state the
        # shared test DB happens to be in. Call-count assertions here would
        # be flaky against other tests' leftover data (same reasoning as
        # the two tests above).
        with patch("app.core.mailer._send_message"):
            booking_jobs.notify_upcoming_booking_status()
