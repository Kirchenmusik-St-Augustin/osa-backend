"""Scheduled jobs for the Booking domain, registered in app.core.scheduler.

Each function opens its own short-lived SessionLocal() -- these run outside
any request context (the documented exception to the SessionLocal-outside-
Depends ruff ban, see pyproject.toml's per-file-ignores and app.core.mailer
for the same pattern). Exceptions are deliberately NOT caught here --
APScheduler's own executor already logs a job's exception and keeps the
scheduler itself running, so an extra `except Exception` here would only
duplicate that (and generic exception handling is banned anyway).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.core import mailer
from app.core.datetime_utils import local_now
from app.db.database import SessionLocal
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.db.models.user import User
from app.services import performance_service


def purge_stale_booking_requests() -> None:
    """Replaces Legacy's `Performance::booted()` anti-pattern (ran on EVERY
    single Model boot, i.e. practically every request touching a
    Performance) -- deletes open booking_requests for performances whose
    schedule has already passed. No grace period, exactly like Legacy."""
    db = SessionLocal()
    try:
        db.execute(
            delete(BookingRequest).where(
                BookingRequest.performance_id.in_(
                    select(Performance.id).where(Performance.schedule < local_now())
                )
            )
        )
        db.commit()
    finally:
        db.close()


def _latest_unnotified_entries(
    logs: Sequence[BookingLog],
) -> dict[tuple[int, int], BookingLog]:
    """Port of `BookingLog::checkNotificationForUpcomingPerformances()`'s
    per-(performance,user) decision: notify only if the latest log entry
    for that user on that performance hasn't been notified yet, AND either
    (a) they were previously notified and the booking_type changed since,
    or (b) they were never notified and the latest entry is a 'book'.
    Keyed by (performance_id, user_id) -- a single user can have
    notify-worthy transitions on SEVERAL upcoming performances at once, all
    of which must survive into one combined mail (see
    notify_upcoming_booking_status)."""
    # Naive datetime.min, deliberately without tzinfo -- our DateTime
    # columns round-trip every value as naive regardless of how it was
    # written (see booking_service._popular_for_position for the same
    # reasoning).
    epoch = datetime.min  # noqa: DTZ901

    by_performance_user: dict[tuple[int, int], list[BookingLog]] = {}
    for log in logs:
        by_performance_user.setdefault((log.performance_id, log.user_id), []).append(
            log
        )

    result: dict[tuple[int, int], BookingLog] = {}
    for key, entries in by_performance_user.items():
        ordered = sorted(entries, key=lambda entry: entry.created_at or epoch)
        latest = ordered[-1]
        if latest.notified_at is not None:
            continue
        previously_notified = [
            entry for entry in ordered if entry.notified_at is not None
        ]
        if previously_notified:
            last_notified = max(
                previously_notified, key=lambda entry: entry.created_at or epoch
            )
            if last_notified.booking_type != latest.booking_type:
                result[key] = latest
        elif latest.booking_type == "book":
            result[key] = latest
    return result


def notify_upcoming_booking_status() -> None:
    """Port of `BookingLog::checkNotificationForUpcomingPerformances()` --
    one `BookingStatus` mail per user, bundling every not-yet-notified
    booking-log transition across all of their upcoming performances."""
    db = SessionLocal()
    try:
        upcoming_performance_ids = list(
            db.execute(select(Performance.id).where(Performance.schedule > local_now()))
            .scalars()
            .all()
        )
        if not upcoming_performance_ids:
            return

        logs = (
            db.execute(
                select(BookingLog).where(
                    BookingLog.performance_id.in_(upcoming_performance_ids)
                )
            )
            .scalars()
            .all()
        )
        if not logs:
            return

        # One notify-worthy entry PER (performance, user) pair, then
        # grouped by user for a single combined mail.
        per_performance_user_entry = _latest_unnotified_entries(logs)
        entries_by_user: dict[int, list[BookingLog]] = {}
        for (_performance_id, user_id), entry in per_performance_user_entry.items():
            entries_by_user.setdefault(user_id, []).append(entry)

        if not entries_by_user:
            return

        users_by_id = {
            user.id: user
            for user in db.execute(
                select(User).where(User.id.in_(entries_by_user.keys()))
            )
            .scalars()
            .all()
        }
        performance_details = {
            performance_id: performance_service.get_performance_detail(
                db, performance_id
            )
            for performance_id in {
                entry.performance_id
                for entries in entries_by_user.values()
                for entry in entries
            }
        }

        now = datetime.now(UTC)
        for user_id, entries in entries_by_user.items():
            user = users_by_id.get(user_id)
            if user is None or user.email is None or user.email_verified_at is None:
                continue
            mail_entries = [
                mailer.BookingStatusMailEntry(
                    ordinariumwork_artist_name=performance_details[
                        entry.performance_id
                    ].ordinariumwork_artist_name,
                    ordinariumwork_name=performance_details[
                        entry.performance_id
                    ].ordinariumwork_name,
                    schedule=performance_details[entry.performance_id].schedule,
                    location_name=performance_details[
                        entry.performance_id
                    ].location.name,
                    location_address=performance_details[
                        entry.performance_id
                    ].location.address,
                    user_name=f"{user.surname}, {user.givenname}",
                    booked=entry.booking_type == "book",
                )
                for entry in entries
            ]
            mailer.send_booking_status_email(user.email, mail_entries)
            for entry in entries:
                entry.notified_at = now
        db.commit()
    finally:
        db.close()
