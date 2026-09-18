"""Scheduled jobs for the Booking domain, registered in
app.worker.settings.WorkerSettings (see app.worker.cron_config for the
shared timing catalog).

Each function opens its own short-lived SessionLocal() -- these run outside
any request context (the documented exception to the SessionLocal-outside-
Depends ruff ban, see pyproject.toml's per-file-ignores and app.core.mailer
for the same pattern). Exceptions are deliberately NOT caught here -- arq's
own Worker.run_job() already logs a job's exception and keeps the worker
itself running, so an extra `except Exception` here would only duplicate
that (and generic exception handling is banned anyway). Their outcome is
recorded by app.worker.scheduled_jobs._run_and_record(), the async wrapper
that actually invokes these functions.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from app.core import mailer
from app.core.datetime_utils import local_now
from app.db.database import SessionLocal
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.db.models.user import User
from app.services import performance_service

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


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
) -> dict[tuple[uuid.UUID, uuid.UUID], BookingLog]:
    """Port of `BookingLog::checkNotificationForUpcomingPerformances()`'s
    per-(performance,user) decision: notify only if the latest log entry
    for that user on that performance hasn't been notified yet, AND either
    (a) they were previously notified and the booking_type changed since,
    or (b) they were never notified and the latest entry is a 'book'.
    Keyed by (performance_id, user_id) -- a single user can have
    notify-worthy transitions on SEVERAL upcoming performances at once, all
    of which must survive into one combined mail (see
    notify_upcoming_booking_status).

    `performance_id`/`user_id` are nullable (ON DELETE SET NULL, see
    app.db.models.booking_log), but every row this function sees was
    already filtered by the caller against a list of currently-existing
    Performance ids -- a NULL performance_id can never satisfy that
    membership test, so the guard below is a type-narrowing measure, not a
    behavior change."""
    # Naive datetime.min, deliberately without tzinfo -- our DateTime
    # columns round-trip every value as naive regardless of how it was
    # written (see booking_service._popular_for_position for the same
    # reasoning).
    epoch = datetime.min  # noqa: DTZ901

    by_performance_user: dict[tuple[uuid.UUID, uuid.UUID], list[BookingLog]] = {}
    for log in logs:
        if log.performance_id is None or log.user_id is None:
            continue
        by_performance_user.setdefault((log.performance_id, log.user_id), []).append(
            log
        )

    result: dict[tuple[uuid.UUID, uuid.UUID], BookingLog] = {}
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


def _capture_entry_data_before_any_commit(
    entries_by_user: dict[uuid.UUID, list[tuple[uuid.UUID, BookingLog]]],
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, list[uuid.UUID]]]:
    """Reads entry.id/entry.booking_type once, before
    mailer.send_booking_status_email()'s own internal db.commit() (see
    _log_sent_email) expires every object in the session's identity map --
    reading either attribute again afterwards would force one extra
    refresh SELECT per entry, scaling with the number of notify-worthy
    entries (found live while adding this module's query-count regression
    test)."""
    booking_type_by_entry_id: dict[uuid.UUID, str] = {}
    entry_ids_by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
    for user_id, pairs in entries_by_user.items():
        entry_ids_by_user[user_id] = [entry.id for _performance_id, entry in pairs]
        for _performance_id, entry in pairs:
            booking_type_by_entry_id[entry.id] = entry.booking_type
    return booking_type_by_entry_id, entry_ids_by_user


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
        # grouped by user for a single combined mail. performance_id is
        # carried alongside each entry (from the already-narrowed tuple
        # key, see _latest_unnotified_entries) instead of re-reading
        # entry.performance_id, which is `uuid.UUID | None` on the model
        # itself.
        per_performance_user_entry = _latest_unnotified_entries(logs)
        entries_by_user: dict[uuid.UUID, list[tuple[uuid.UUID, BookingLog]]] = {}
        for (performance_id, user_id), entry in per_performance_user_entry.items():
            entries_by_user.setdefault(user_id, []).append((performance_id, entry))

        if not entries_by_user:
            return

        booking_type_by_entry_id, entry_ids_by_user = (
            _capture_entry_data_before_any_commit(entries_by_user)
        )

        users_by_id = {
            user.id: user
            for user in db.execute(
                select(User).where(User.id.in_(entries_by_user.keys()))
            )
            .scalars()
            .all()
        }
        # N+1-safe: one query for the Performance rows themselves, then
        # performance_service's shared batch loader for
        # Location/Ordinariumwork/Artist -- a fixed number of queries
        # regardless of how many performances are involved, instead of
        # get_performance_detail()'s ~5 queries PER performance_id (same
        # loader booking_service.py uses for its own performance listing).
        needed_performance_ids = {
            performance_id
            for pairs in entries_by_user.values()
            for performance_id, _entry in pairs
        }
        performances = (
            db.execute(
                select(Performance).where(Performance.id.in_(needed_performance_ids))
            )
            .scalars()
            .all()
        )
        performance_batch = performance_service.load_performance_batch_data(
            db, performances
        )
        schedule_by_performance = {
            performance.id: performance.schedule for performance in performances
        }

        now = datetime.now(UTC)
        for user_id, pairs in entries_by_user.items():
            user = users_by_id.get(user_id)
            if user is None or user.email is None or user.email_verified_at is None:
                continue
            mail_entries = [
                mailer.BookingStatusMailEntry(
                    ordinariumwork_artist_name=performance_batch[
                        performance_id
                    ].ordinariumwork_artist_name,
                    ordinariumwork_name=performance_batch[
                        performance_id
                    ].ordinariumwork_name,
                    schedule=schedule_by_performance[performance_id],
                    location_name=performance_batch[performance_id].location.name,
                    location_address=performance_batch[performance_id].location.address,
                    user_name=f"{user.surname}, {user.givenname}",
                    booked=booking_type_by_entry_id[entry.id] == "book",
                )
                for performance_id, entry in pairs
            ]
            mailer.send_booking_status_email(user.email, mail_entries)
            # Bulk UPDATE by id instead of assigning entry.notified_at on
            # each (by now possibly session-expired) ORM object -- avoids
            # the same per-entry refresh-SELECT the booking_type capture
            # above avoids, and collapses what would be one UPDATE per
            # entry into one per user. synchronize_session=False: none of
            # these BookingLog objects are read again in this function, so
            # there is nothing to keep in sync -- without it, the ORM's
            # default "auto" strategy falls back to a per-row SELECT before
            # the UPDATE to figure out which loaded objects to refresh.
            db.execute(
                update(BookingLog)
                .where(BookingLog.id.in_(entry_ids_by_user[user_id]))
                .values(notified_at=now)
                .execution_options(synchronize_session=False)
            )
        db.commit()
    finally:
        db.close()
