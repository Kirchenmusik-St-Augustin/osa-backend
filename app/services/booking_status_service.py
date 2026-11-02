from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.core import mailer
from app.core.datetime_utils import local_now
from app.core.human_names import label_for_name
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.performance_position import PerformancePosition
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.db.models.user_role import UserRole
from app.schemas.base import IdNameOutput
from app.schemas.performance import BookingStatus, BookingStatusOutput
from app.services import performance_service
from app.services.booking_common import (
    ensure_not_past,
    get_performance_or_404,
    position_names_batch,
    quantities_for_performance,
    setup_position_ids,
)
from app.services.cast_service import CastEntry, save_cast_item
from app.services.position_types import (
    POSITION_TYPES,
    PositionType,
    position_column,
    position_key,
)
from app.services.user_position_service import is_bookable

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.db.models.performance import Performance


class BookingRequestAlreadyExistsError(Exception):
    """Defensive guard against a race between two concurrent self-service
    requests for the same performance -- unreachable in the normal
    single-user flow since change_user_request_status only dispatches here
    when user_booking_status() already reported BOOKABLE (no existing row)."""


@dataclass(frozen=True)
class BookedOrStandbyCanceledNotification:
    """Everything the router needs to enqueue
    `send_booked_or_standby_canceled_email_task` via `JobQueue.enqueue(...)`
    -- kept as plain data so the service layer itself never imports FastAPI
    (see change_user_request_status)."""

    disponent_emails: list[str]
    canceling_user_name: str
    entry: mailer.BookingCanceledMailEntry


def user_booking_status(
    db: Session,
    performance: Performance,
    user_id: uuid.UUID,
    *,
    keep_past_status: bool = False,
) -> BookingStatusOutput:
    return user_booking_status_batch(
        db, performance, [user_id], keep_past_status=keep_past_status
    )[user_id]


def get_my_booking_status(
    db: Session, performance_id: uuid.UUID, user_id: uuid.UUID
) -> BookingStatusOutput:
    """Public entry point for `GET /performances/{id}/my-booking-status` --
    deliberately its own small endpoint+service function (not a retrofit of
    performance_service.get_performance_detail) to keep performance_service
    and the booking modules decoupled at module-import time. Always reveals the
    real status even for a past performance -- the Show page needs to
    render the self-service badge/trigger regardless of date."""
    performance = get_performance_or_404(db, performance_id)
    return user_booking_status(db, performance, user_id, keep_past_status=True)


def user_booking_status_batch(
    db: Session,
    performance: Performance,
    user_ids: list[uuid.UUID],
    *,
    keep_past_status: bool = False,
) -> dict[uuid.UUID, BookingStatusOutput]:
    """N+1-safe: a fixed, small number of queries regardless of how many
    user_ids are passed in."""
    if not user_ids:
        return {}
    if performance.schedule < local_now() and not keep_past_status:
        return {
            user_id: BookingStatusOutput(status=BookingStatus.NOT_BOOKABLE)
            for user_id in user_ids
        }

    setup_ids = setup_position_ids(performance_service.get_setup(db, performance.id))

    user_positions = (
        db.execute(select(UserPosition).where(UserPosition.user_id.in_(user_ids)))
        .scalars()
        .all()
    )
    user_position_ids: dict[uuid.UUID, dict[PositionType, set[uuid.UUID]]] = {
        user_id: {position_type: set() for position_type in POSITION_TYPES}
        for user_id in user_ids
    }
    for user_position in user_positions:
        position_type, position_id = position_key(user_position)
        user_position_ids[user_position.user_id][position_type].add(position_id)

    bookings = (
        db.execute(
            select(Booking).where(
                Booking.performance_id == performance.id, Booking.user_id.in_(user_ids)
            )
        )
        .scalars()
        .all()
    )
    bookings_by_user = {booking.user_id: booking for booking in bookings}

    requests = (
        db.execute(
            select(BookingRequest).where(
                BookingRequest.performance_id == performance.id,
                BookingRequest.user_id.in_(user_ids),
            )
        )
        .scalars()
        .all()
    )
    requests_by_user = {request.user_id: request for request in requests}

    quantity_by_key = quantities_for_performance(db, performance.id)
    name_by_key = position_names_batch(
        db, {position_key(booking) for booking in bookings}
    )

    result: dict[uuid.UUID, BookingStatusOutput] = {}
    for user_id in user_ids:
        if not is_bookable(user_position_ids[user_id], setup_ids):
            result[user_id] = BookingStatusOutput(status=BookingStatus.NOT_BOOKABLE)
            continue

        booking = bookings_by_user.get(user_id)
        if booking is not None:
            booking_key = position_key(booking)
            quantity = quantity_by_key.get(booking_key, 0)
            name = name_by_key.get(booking_key, "")
            result[user_id] = BookingStatusOutput(
                status=(
                    BookingStatus.BOOKED
                    if booking.order < quantity
                    else BookingStatus.STANDBY
                ),
                position=IdNameOutput(id=booking_key[1], name=name),
                # updated_at is NULL until the row's first real UPDATE
                # (the set_updated_at() trigger never fires on a row that
                # was only ever inserted, never modified in place -- see
                # save_cast_item's delete+recreate pattern) -- created_at
                # is the meaningful fallback.
                at=booking.updated_at or booking.created_at,
            )
            continue

        booking_request = requests_by_user.get(user_id)
        if booking_request is not None:
            at = booking_request.updated_at or booking_request.created_at
            result[user_id] = (
                BookingStatusOutput(status=BookingStatus.REJECTED, at=at)
                if booking_request.notbooked_at is not None
                else BookingStatusOutput(status=BookingStatus.REQUESTED, at=at)
            )
            continue

        result[user_id] = BookingStatusOutput(status=BookingStatus.BOOKABLE)
    return result


def user_booking_status_for_performances(
    db: Session,
    performances: list[Performance],
    user_id: uuid.UUID,
    *,
    keep_past_status: bool = False,
) -> dict[uuid.UUID, BookingStatusOutput]:
    """N+1-safe variant of user_booking_status_batch() for the other axis:
    ONE user across MANY performances -- what the calendar list needs for
    its self-service badge/trigger on every row, computed in a fixed number
    of queries.

    `keep_past_status`: every caller so far passes nothing (past
    performances always collapse to NOT_BOOKABLE), EXCEPT the admin per-user
    "Anfragen und Buchungen" view, which passes True so historic bookings
    still show their real status instead of going blank."""
    if not performances:
        return {}

    result: dict[uuid.UUID, BookingStatusOutput] = {
        performance.id: BookingStatusOutput(status=BookingStatus.NOT_BOOKABLE)
        for performance in performances
    }
    eligible_ids = [
        performance.id
        for performance in performances
        if keep_past_status or performance.schedule >= local_now()
    ]
    if not eligible_ids:
        return result

    setup_rows = (
        db.execute(
            select(PerformancePosition).where(
                PerformancePosition.performance_id.in_(eligible_ids)
            )
        )
        .scalars()
        .all()
    )
    setup_ids_by_performance: dict[uuid.UUID, dict[PositionType, set[uuid.UUID]]] = {
        performance_id: {position_type: set() for position_type in POSITION_TYPES}
        for performance_id in eligible_ids
    }
    quantity_by_performance: dict[
        uuid.UUID, dict[tuple[PositionType, uuid.UUID], int]
    ] = {performance_id: {} for performance_id in eligible_ids}
    for row in setup_rows:
        row_key = position_key(row)
        setup_ids_by_performance[row.performance_id][row_key[0]].add(row_key[1])
        quantity_by_performance[row.performance_id][row_key] = row.quantity

    user_positions = (
        db.execute(select(UserPosition).where(UserPosition.user_id == user_id))
        .scalars()
        .all()
    )
    user_position_ids: dict[PositionType, set[uuid.UUID]] = {
        position_type: set() for position_type in POSITION_TYPES
    }
    for user_position in user_positions:
        position_type, position_id = position_key(user_position)
        user_position_ids[position_type].add(position_id)

    bookings = (
        db.execute(
            select(Booking).where(
                Booking.user_id == user_id, Booking.performance_id.in_(eligible_ids)
            )
        )
        .scalars()
        .all()
    )
    bookings_by_performance = {booking.performance_id: booking for booking in bookings}

    requests = (
        db.execute(
            select(BookingRequest).where(
                BookingRequest.user_id == user_id,
                BookingRequest.performance_id.in_(eligible_ids),
            )
        )
        .scalars()
        .all()
    )
    requests_by_performance = {request.performance_id: request for request in requests}

    name_by_key = position_names_batch(
        db, {position_key(booking) for booking in bookings}
    )

    for performance_id in eligible_ids:
        result[performance_id] = _resolve_calendar_status(
            performance_id,
            user_position_ids=user_position_ids,
            setup_ids_by_performance=setup_ids_by_performance,
            quantity_by_performance=quantity_by_performance,
            bookings_by_performance=bookings_by_performance,
            requests_by_performance=requests_by_performance,
            name_by_key=name_by_key,
        )

    return result


def _resolve_calendar_status(
    performance_id: uuid.UUID,
    *,
    user_position_ids: dict[PositionType, set[uuid.UUID]],
    setup_ids_by_performance: dict[uuid.UUID, dict[PositionType, set[uuid.UUID]]],
    quantity_by_performance: dict[uuid.UUID, dict[tuple[PositionType, uuid.UUID], int]],
    bookings_by_performance: dict[uuid.UUID, Booking],
    requests_by_performance: dict[uuid.UUID, BookingRequest],
    name_by_key: dict[tuple[PositionType, uuid.UUID], str],
) -> BookingStatusOutput:
    """Pure per-row decision extracted from user_booking_status_for_
    performances() -- same branching as user_booking_status_batch()'s inline
    loop, just against the already-batched-by-performance dicts."""
    if not is_bookable(user_position_ids, setup_ids_by_performance[performance_id]):
        return BookingStatusOutput(status=BookingStatus.NOT_BOOKABLE)

    booking = bookings_by_performance.get(performance_id)
    if booking is not None:
        booking_key = position_key(booking)
        quantity = quantity_by_performance[performance_id].get(booking_key, 0)
        name = name_by_key.get(booking_key, "")
        return BookingStatusOutput(
            status=(
                BookingStatus.BOOKED
                if booking.order < quantity
                else BookingStatus.STANDBY
            ),
            position=IdNameOutput(id=booking_key[1], name=name),
            # See user_booking_status_batch's identical fallback above --
            # updated_at is NULL on a row that was only ever inserted.
            at=booking.updated_at or booking.created_at,
        )

    booking_request = requests_by_performance.get(performance_id)
    if booking_request is not None:
        at = booking_request.updated_at or booking_request.created_at
        return (
            BookingStatusOutput(status=BookingStatus.REJECTED, at=at)
            if booking_request.notbooked_at is not None
            else BookingStatusOutput(status=BookingStatus.REQUESTED, at=at)
        )

    return BookingStatusOutput(status=BookingStatus.BOOKABLE)


def _disponent_emails(db: Session) -> list[str]:
    rows = (
        db.execute(
            select(User.email)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "disponent", User.email.is_not(None))
        )
        .scalars()
        .all()
    )
    return [email for email in rows if email is not None]


def _build_canceled_notification(
    db: Session, performance: Performance, user: User, current: BookingStatusOutput
) -> BookedOrStandbyCanceledNotification | None:
    """Builds the (recipients, sender name, mail entry) tuple the ROUTER
    enqueues via `JobQueue.enqueue(...)` -- returns None if there is
    nothing to send. The service layer stays framework-agnostic (no FastAPI
    import), matching every other service module in this codebase (e.g.
    auth_service.py's request_password_reset(), whose router caller decides
    whether/how to enqueue the background job)."""
    disponent_emails = _disponent_emails(db)
    if not disponent_emails:
        return None
    detail = performance_service.get_performance_detail(db, performance.id)
    entry = mailer.BookingCanceledMailEntry(
        ordinariumwork_artist_name=detail.ordinariumwork_artist_name,
        ordinariumwork_name=detail.ordinariumwork_name,
        schedule=detail.schedule,
        location_name=detail.location.name,
        location_address=detail.location.address,
        previous_status=current.status,
        position_name=current.position.name if current.position else "",
    )
    return BookedOrStandbyCanceledNotification(
        disponent_emails=disponent_emails,
        canceling_user_name=label_for_name(user.surname, user.givenname),
        entry=entry,
    )


def cancel_auth_user_booking(
    db: Session, performance_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Rebuilds the remaining cast list for the user's (former) position
    (without them) and re-runs it through save_cast_item, which
    automatically promotes the next standby entry and logs accordingly."""
    booking = db.execute(
        select(Booking).where(
            Booking.performance_id == performance_id, Booking.user_id == user_id
        )
    ).scalar_one_or_none()
    if booking is None:
        return

    position_type, position_id = position_key(booking)
    remaining = (
        db.execute(
            select(Booking)
            .where(
                Booking.performance_id == performance_id,
                position_column(Booking, position_type) == position_id,
                Booking.id != booking.id,
            )
            .order_by(Booking.order)
        )
        .scalars()
        .all()
    )
    entries: list[CastEntry] = [(row.user_id, row.fee) for row in remaining]
    save_cast_item(
        db,
        performance_id,
        position_type,
        position_id,
        new_cast=entries,
        old_quantity=None,
    )


def _request_booking(
    db: Session, performance_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    existing = db.execute(
        select(BookingRequest).where(
            BookingRequest.performance_id == performance_id,
            BookingRequest.user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BookingRequestAlreadyExistsError
    db.add(
        BookingRequest(
            performance_id=performance_id,
            user_id=user_id,
        )
    )


def _cancel_booking_or_request(
    db: Session, performance: Performance, user: User, current: BookingStatusOutput
) -> BookedOrStandbyCanceledNotification | None:
    notification = (
        _build_canceled_notification(db, performance, user, current)
        if current.status in (BookingStatus.STANDBY, BookingStatus.BOOKED)
        else None
    )
    db.execute(
        delete(BookingRequest).where(
            BookingRequest.performance_id == performance.id,
            BookingRequest.user_id == user.id,
        )
    )
    cancel_auth_user_booking(db, performance.id, user.id)
    return notification


def change_user_request_status(
    db: Session, performance_id: uuid.UUID, user: User
) -> tuple[BookingStatusOutput, BookedOrStandbyCanceledNotification | None]:
    """Takes no client-provided target status: the server recomputes the
    CURRENT status itself via user_booking_status() and dispatches on that.
    A client can never dictate an arbitrary transition.

    Returns the notification descriptor (or None) for the ROUTER to
    enqueue via `job_queue.enqueue(..., notification.disponent_emails,
    notification.canceling_user_name, notification.entry)` -- the
    descriptor captures the OLD status before this function's own
    db.commit() below."""
    performance = get_performance_or_404(db, performance_id, lock=True)
    ensure_not_past(performance)
    current = user_booking_status(db, performance, user.id)

    notification: BookedOrStandbyCanceledNotification | None = None
    if current.status == BookingStatus.BOOKABLE:
        _request_booking(db, performance_id, user.id)
    elif current.status != BookingStatus.NOT_BOOKABLE:
        notification = _cancel_booking_or_request(db, performance, user, current)
    # NOT_BOOKABLE: no matching case -- a silent no-op.

    db.commit()
    return user_booking_status(db, performance, user.id), notification
