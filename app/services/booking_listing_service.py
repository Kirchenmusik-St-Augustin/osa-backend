from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.datetime_utils import local_now
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.schemas.booking import (
    PerformanceRequestsAndBookingsResponse,
    PerformanceShortOutput,
    RequestOrBookingEntryOutput,
)
from app.schemas.pagination import PagedRows
from app.services import performance_service
from app.services.booking_common import (
    display_name,
    ensure_not_past,
    get_performance_or_404,
    load_users_by_id,
    to_short_output,
)
from app.services.booking_status_service import (
    user_booking_status,
    user_booking_status_batch,
    user_booking_status_for_performances,
)
from app.services.pagination import select_page

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.db.models.user import User
    from app.schemas.pagination import PageParams


def get_requests_and_bookings(
    db: Session, performance_id: uuid.UUID, current_user: User
) -> PerformanceRequestsAndBookingsResponse:
    performance = get_performance_or_404(db, performance_id)
    ensure_not_past(performance)
    detail = performance_service.get_performance_detail(db, performance_id)

    booked_user_ids = list(
        db.execute(
            select(Booking.user_id)
            .where(Booking.performance_id == performance_id)
            .distinct()
        )
        .scalars()
        .all()
    )
    requesting_user_ids = list(
        db.execute(
            select(BookingRequest.user_id).where(
                BookingRequest.performance_id == performance_id
            )
        )
        .scalars()
        .all()
    )
    ordered_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for user_id in booked_user_ids + requesting_user_ids:
        if user_id not in seen:
            seen.add(user_id)
            ordered_ids.append(user_id)

    statuses = user_booking_status_batch(db, performance, ordered_ids)
    users_by_id = load_users_by_id(db, set(ordered_ids))
    entries = [
        RequestOrBookingEntryOutput(
            id=user_id,
            name=display_name(users_by_id.get(user_id)),
            status=statuses[user_id],
        )
        for user_id in ordered_ids
    ]

    user_booking = user_booking_status(db, performance, current_user.id)
    short = to_short_output(detail, user_booking)
    return PerformanceRequestsAndBookingsResponse(**short.model_dump(), entries=entries)


def get_upcoming_requests_and_bookings_for_user(
    db: Session, user_id: uuid.UUID, page: PageParams, *, upcoming_only: bool = True
) -> PagedRows[PerformanceShortOutput]:
    """Every Performance the user has either a confirmed Booking for, or
    (failing that) an open BookingRequest for -- Bookings take precedence
    on the rare case both exist for the same performance ("booked ids
    first, then requesting ids not already covered" de-dup order; no
    filter on BookingRequest.notbooked_at, rejected requests are included
    too).

    `upcoming_only` defaults to True (the Selfadmin/Support caller), but
    the admin per-user "Anfragen und Buchungen" view (`GET
    /users/{id}/requests-and-bookings`) passes False for the ALL-history
    variant. Generic on `user_id` (not necessarily the caller) so this one
    function backs both callers."""
    now = local_now()
    booked_query = (
        select(Booking.performance_id)
        .join(Performance, Performance.id == Booking.performance_id)
        .where(Booking.user_id == user_id)
        .distinct()
    )
    requested_query = (
        select(BookingRequest.performance_id)
        .join(Performance, Performance.id == BookingRequest.performance_id)
        .where(BookingRequest.user_id == user_id)
    )
    if upcoming_only:
        booked_query = booked_query.where(Performance.schedule >= now)
        requested_query = requested_query.where(Performance.schedule >= now)
    booked_ids = list(db.execute(booked_query).scalars().all())
    requested_ids = list(db.execute(requested_query).scalars().all())
    ordered_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for performance_id in booked_ids + requested_ids:
        if performance_id not in seen:
            seen.add(performance_id)
            ordered_ids.append(performance_id)
    if not ordered_ids:
        return PagedRows(rows=[], total=0)

    performances_page = select_page(
        db,
        select(Performance)
        .where(Performance.id.in_(ordered_ids))
        .order_by(Performance.schedule, Performance.id),
        page,
    )
    performances = performances_page.rows
    batch = performance_service.load_performance_batch_data(db, performances)
    user_booking_by_performance = user_booking_status_for_performances(
        db, list(performances), user_id, keep_past_status=not upcoming_only
    )

    return performances_page.map(
        lambda performance: PerformanceShortOutput(
            id=performance.id,
            ordinariumwork_name=batch[performance.id].ordinariumwork_name,
            ordinariumwork_artist_name=batch[performance.id].ordinariumwork_artist_name,
            artist_name=batch[performance.id].artist_name,
            schedule=performance.schedule,
            location=batch[performance.id].location,
            user_booking=user_booking_by_performance[performance.id],
            proprium=batch[performance.id].proprium,
            demanding_proprium=batch[performance.id].demanding_proprium,
            rehearsals=batch[performance.id].rehearsals,
        )
    )
