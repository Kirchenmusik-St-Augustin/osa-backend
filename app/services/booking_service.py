from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import mailer
from app.core.datetime_utils import local_now
from app.core.human_names import label_for_name
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.db.models.user_role import UserRole
from app.db.models.voice import Voice
from app.schemas.booking import (
    BillingExtracostOutput,
    BillingItemOutput,
    BillingOrgfeeOutput,
    BillingOutput,
    BillingPositionOutput,
    BillingTypeOutput,
    BookableGroupOutput,
    BookableUserOutput,
    CastFormData,
    CastMemberOutput,
    CastSaveRequest,
    CastSectionInput,
    CastSectionOutput,
    CastSetupItemInput,
    CastSetupItemOutput,
    MessageRecipientOutput,
    NotBookedOutput,
    PerformanceBillingResponse,
    PerformanceCastPageResponse,
    PerformanceMessageToCastResponse,
    PerformanceRequestsAndBookingsResponse,
    PerformanceShortOutput,
    PopularFrequentUserOutput,
    PopularItemOutput,
    PopularRecentUserOutput,
    PopularSectionOutput,
    RequestOrBookingEntryOutput,
    SendMessageRequest,
    StaffItemOutput,
    StaffSectionOutput,
)
from app.schemas.performance import (
    BookingStatusOutput,
    PerformancePositionOutput,
    PerformanceSetupOutput,
    PerformanceShowResponse,
    PositionRefOutput,
)
from app.services import fee_service, ordinariumwork_service, performance_service
from app.services.performance_service import (
    PerformanceInPastError,
    PerformanceNotFoundError,
)
from app.services.position_types import POSITION_MODELS, POSITION_TYPES, PositionType
from app.services.user_position_service import (
    get_qualified_user_ids_batch,
    is_bookable,
)

# (user_id, fee) -- the internal exchange shape saveCastItem's diff engine
# works with, decoupled from the CastMemberInput/-Output Pydantic schemas
# that only exist at the HTTP boundary (reconcile_setup_change and
# cancel_auth_user_booking build these from ORM rows, not request bodies).
CastEntry = tuple[int, int]

# Fixed business constants from Legacy's config/osa.php ("billing" section)
# -- not user-editable Settings fields, same reasoning as
# Performance.instrument_defaultfee being a real column rather than config.
_INSTRUMENTS_ORGFEE_TIER1_THRESHOLD = 0
_INSTRUMENTS_ORGFEE_TIER1 = 30
_INSTRUMENTS_ORGFEE_TIER2_THRESHOLD = 12
_INSTRUMENTS_ORGFEE_TIER2 = 55
_CHOIRJOBS_ORGFEE_THRESHOLD = 0
_CHOIRJOBS_ORGFEE = 15


class BookingRequestAlreadyExistsError(Exception):
    """Defensive guard against a race between two concurrent self-service
    requests for the same performance -- unreachable in the normal
    single-user flow since change_user_request_status only dispatches here
    when userBookingStatus() already reported status 1 (no existing row)."""


class MessageRecipientsEmptyError(Exception):
    """Raised when none of the requested recipients have a verified email
    -- mirrors the same "nothing to actually send" guard as Legacy's
    `hasVerifiedEmail()` check in messageToContactperson/BookingLog."""


@dataclass(frozen=True)
class BookedOrStandbyCanceledNotification:
    """Everything the router needs to schedule
    `mailer.send_booked_or_standby_canceled_email` via `BackgroundTasks.
    add_task(...)` -- kept as plain data so the service layer itself never
    imports FastAPI (see change_user_request_status)."""

    disponent_emails: list[str]
    canceling_user_name: str
    entry: mailer.BookingCanceledMailEntry


# --- shared helpers ----------------------------------------------------------


def _get_performance_or_404(db: Session, performance_id: int) -> Performance:
    result = db.execute(select(Performance).where(Performance.id == performance_id))
    performance = result.scalar_one_or_none()
    if performance is None:
        raise PerformanceNotFoundError
    return performance


def _ensure_not_past(performance: Performance) -> None:
    if performance.schedule < local_now():
        raise PerformanceInPastError


def _setup_position_ids(setup: PerformanceSetupOutput) -> dict[PositionType, set[int]]:
    return {
        "instruments": {item.id for item in setup.instruments},
        "voices": {item.id for item in setup.voices},
        "choirjobs": {item.id for item in setup.choirjobs},
    }


def _users_by_id(db: Session, user_ids: set[int]) -> dict[int, User]:
    """Includes soft-deleted users -- for displaying an EXISTING booking's/
    request's user, which must never crash on a deactivated account
    (Schritt-5 withTrashed()-consistency decision, applied here to every
    Booking display in Schritt 6 too)."""
    if not user_ids:
        return {}
    rows = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    return {user.id: user for user in rows}


def _active_users_by_id(db: Session, user_ids: set[int]) -> dict[int, User]:
    """Excludes soft-deleted users -- for NEW-booking candidate/suggestion
    lists (staff() bookable, popularBookings(), notbooked()'s GET side),
    matching Legacy's own relation scoping there (no withTrashed() call)."""
    if not user_ids:
        return {}
    rows = (
        db.execute(select(User).where(User.id.in_(user_ids), User.deleted_at.is_(None)))
        .scalars()
        .all()
    )
    return {user.id: user for user in rows}


def _primary_voice_by_user(db: Session, user_ids: set[int]) -> dict[int, Voice]:
    """Each user's lowest-`Voice.order` assigned Voice (their "primary"
    voice for choirjob auto-sort) via UserPosition -- N+1-safe: exactly one
    UserPosition query + one Voice query, regardless of how many user_ids
    come in. A user CAN hold multiple `voices`-type UserPosition rows (no
    DB constraint prevents it -- UserPosition's only unique constraint is
    the full (user_id, position_type, position_id) triple); the
    lowest-`order` one wins, matching performance_service.get_setup()'s own
    `.order_by(Voice.order, Voice.id)` canonical-ordering idiom."""
    if not user_ids:
        return {}
    voice_ids_by_user: dict[int, set[int]] = {}
    rows = db.execute(
        select(UserPosition.user_id, UserPosition.position_id).where(
            UserPosition.user_id.in_(user_ids),
            UserPosition.position_type == "voices",
        )
    ).all()
    for user_id, position_id in rows:
        voice_ids_by_user.setdefault(user_id, set()).add(position_id)
    if not voice_ids_by_user:
        return {}

    all_voice_ids = {vid for ids in voice_ids_by_user.values() for vid in ids}
    voices_in_order = (
        db.execute(
            select(Voice)
            .where(Voice.id.in_(all_voice_ids))
            .order_by(Voice.order, Voice.id)
        )
        .scalars()
        .all()
    )
    rank_by_voice_id = {voice.id: rank for rank, voice in enumerate(voices_in_order)}
    voice_by_id = {voice.id: voice for voice in voices_in_order}

    return {
        user_id: voice_by_id[min(voice_ids, key=lambda vid: rank_by_voice_id[vid])]
        for user_id, voice_ids in voice_ids_by_user.items()
    }


def _choirjob_voice_fields(
    position_type: PositionType, user_id: int, primary_voice_by_user: dict[int, Voice]
) -> tuple[str | None, int | None]:
    """Voice fields only ever populated for choirjobs -- instruments/voices
    cast members and candidates keep both fields None."""
    if position_type != "choirjobs":
        return None, None
    voice = primary_voice_by_user.get(user_id)
    return (voice.name, voice.order) if voice is not None else (None, None)


def _display_name(user: User | None) -> str:
    if user is None:
        return "N. N."
    return label_for_name(user.surname, user.givenname)


def _position_names_batch(
    db: Session, keys: set[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """Keyed by plain `str`, not the `PositionType` Literal -- these keys
    originate from `Booking.position_type`, a `Mapped[str]` column (the
    Literal only exists at the Python type level for values we construct
    ourselves, not for values read back from the DB; the CHECK constraint
    enforces the invariant at the DB layer instead)."""
    result: dict[tuple[str, int], str] = {}
    ids_by_type: dict[str, set[int]] = {}
    for position_type, position_id in keys:
        ids_by_type.setdefault(position_type, set()).add(position_id)
    for position_type, ids in ids_by_type.items():
        model = POSITION_MODELS[cast("PositionType", position_type)]
        rows = db.execute(select(model.id, model.name).where(model.id.in_(ids))).all()
        for item_id, name in rows:
            result[(position_type, item_id)] = name
    return result


def _quantities_for_performance(
    db: Session, performance_id: int
) -> dict[tuple[str, int], int]:
    rows = (
        db.execute(
            select(PerformancePosition).where(
                PerformancePosition.performance_id == performance_id
            )
        )
        .scalars()
        .all()
    )
    return {(row.position_type, row.position_id): row.quantity for row in rows}


def _to_short_output(
    detail: PerformanceShowResponse, user_booking: BookingStatusOutput
) -> PerformanceShortOutput:
    return PerformanceShortOutput(
        id=detail.id,
        ordinariumwork_name=detail.ordinariumwork_name,
        ordinariumwork_artist_name=detail.ordinariumwork_artist_name,
        artist_name=detail.artist_name,
        schedule=detail.schedule,
        location=detail.location,
        user_booking=user_booking,
        proprium=detail.proprium,
        demanding_proprium=detail.demanding_proprium,
        rehearsals=detail.rehearsals,
    )


# --- userBookingStatus() -- the 6-state machine -----------------------------


def user_booking_status(
    db: Session,
    performance: Performance,
    user_id: int,
    *,
    keep_past_status: bool = False,
) -> BookingStatusOutput:
    return user_booking_status_batch(
        db, performance, [user_id], keep_past_status=keep_past_status
    )[user_id]


def get_my_booking_status(
    db: Session, performance_id: int, user_id: int
) -> BookingStatusOutput:
    """Public entry point for `GET /performances/{id}/my-booking-status` --
    deliberately its own small endpoint+service function (not a retrofit of
    performance_service.get_performance_detail) to keep performance_service
    and booking_service decoupled at module-import time (Schritt 6 plan
    B.4). Always reveals
    the real status even for a past performance -- the Show page needs to
    render the self-service badge/trigger regardless of date."""
    performance = _get_performance_or_404(db, performance_id)
    return user_booking_status(db, performance, user_id, keep_past_status=True)


def user_booking_status_batch(
    db: Session,
    performance: Performance,
    user_ids: list[int],
    *,
    keep_past_status: bool = False,
) -> dict[int, BookingStatusOutput]:
    """N+1-safe: a fixed, small number of queries regardless of how many
    user_ids are passed in -- mirrors Performance::userBookingStatus()
    called once per user in Legacy's requestsAndBookings(), but without
    the N+1 (Schritt 6 plan A.8)."""
    if not user_ids:
        return {}
    if performance.schedule < local_now() and not keep_past_status:
        return {user_id: BookingStatusOutput(status=0) for user_id in user_ids}

    setup_ids = _setup_position_ids(performance_service.get_setup(db, performance.id))

    user_position_rows = db.execute(
        select(
            UserPosition.user_id, UserPosition.position_type, UserPosition.position_id
        ).where(UserPosition.user_id.in_(user_ids))
    ).all()
    user_position_ids: dict[int, dict[PositionType, set[int]]] = {
        user_id: {position_type: set() for position_type in POSITION_TYPES}
        for user_id in user_ids
    }
    for user_id, position_type, position_id in user_position_rows:
        # cast(): position_type is Mapped[str] on UserPosition (a DB CHECK
        # constraint enforces the invariant, not the Python type) -- see
        # _position_names_batch's docstring for the same reasoning.
        user_position_ids[user_id][cast("PositionType", position_type)].add(position_id)

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

    quantity_by_key = _quantities_for_performance(db, performance.id)
    name_by_key = _position_names_batch(
        db, {(booking.position_type, booking.position_id) for booking in bookings}
    )

    result: dict[int, BookingStatusOutput] = {}
    for user_id in user_ids:
        if not is_bookable(user_position_ids[user_id], setup_ids):
            result[user_id] = BookingStatusOutput(status=0)
            continue

        booking = bookings_by_user.get(user_id)
        if booking is not None:
            quantity = quantity_by_key.get(
                (booking.position_type, booking.position_id), 0
            )
            name = name_by_key.get((booking.position_type, booking.position_id), "")
            result[user_id] = BookingStatusOutput(
                status=4 if booking.order < quantity else 3,
                position=PositionRefOutput(id=booking.position_id, name=name),
                at=booking.updated_at,
            )
            continue

        booking_request = requests_by_user.get(user_id)
        if booking_request is not None:
            result[user_id] = (
                BookingStatusOutput(status=5, at=booking_request.updated_at)
                if booking_request.notbooked_at is not None
                else BookingStatusOutput(status=2, at=booking_request.updated_at)
            )
            continue

        result[user_id] = BookingStatusOutput(status=1)
    return result


def user_booking_status_for_performances(
    db: Session,
    performances: list[Performance],
    user_id: int,
    *,
    keep_past_status: bool = False,
) -> dict[int, BookingStatusOutput]:
    """N+1-safe variant of user_booking_status_batch() for the other axis:
    ONE user across MANY performances -- what the calendar list needs for
    its self-service badge/trigger on every row. Legacy's own equivalent
    (Short resource's `auth_user_booking` accessor) runs userBookingStatus()
    once per row, a real N+1 there; the project's N+1-protection
    requirement means the business RESULT is ported here, not that query
    pattern (Schritt 6 plan A.8).

    `keep_past_status` mirrors Legacy's `userBookingStatus($user,
    $keepPastStatus)` second argument: every caller so far passes nothing
    (past performances always collapse to status=0), EXCEPT the System-
    admin per-user "Anfragen und Buchungen" view, which calls `...(true)`
    so historic bookings still show their real status instead of going
    blank."""
    if not performances:
        return {}

    result: dict[int, BookingStatusOutput] = {
        performance.id: BookingStatusOutput(status=0) for performance in performances
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
    setup_ids_by_performance: dict[int, dict[PositionType, set[int]]] = {
        performance_id: {position_type: set() for position_type in POSITION_TYPES}
        for performance_id in eligible_ids
    }
    quantity_by_performance: dict[int, dict[tuple[str, int], int]] = {
        performance_id: {} for performance_id in eligible_ids
    }
    for row in setup_rows:
        setup_ids_by_performance[row.performance_id][
            cast("PositionType", row.position_type)
        ].add(row.position_id)
        quantity_by_performance[row.performance_id][
            (row.position_type, row.position_id)
        ] = row.quantity

    user_position_rows = db.execute(
        select(UserPosition.position_type, UserPosition.position_id).where(
            UserPosition.user_id == user_id
        )
    ).all()
    user_position_ids: dict[PositionType, set[int]] = {
        position_type: set() for position_type in POSITION_TYPES
    }
    for position_type, position_id in user_position_rows:
        user_position_ids[cast("PositionType", position_type)].add(position_id)

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

    name_by_key = _position_names_batch(
        db, {(booking.position_type, booking.position_id) for booking in bookings}
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
    performance_id: int,
    *,
    user_position_ids: dict[PositionType, set[int]],
    setup_ids_by_performance: dict[int, dict[PositionType, set[int]]],
    quantity_by_performance: dict[int, dict[tuple[str, int], int]],
    bookings_by_performance: dict[int, Booking],
    requests_by_performance: dict[int, BookingRequest],
    name_by_key: dict[tuple[str, int], str],
) -> BookingStatusOutput:
    """Pure per-row decision extracted from user_booking_status_for_
    performances() -- same branching as user_booking_status_batch()'s inline
    loop, just against the already-batched-by-performance dicts."""
    if not is_bookable(user_position_ids, setup_ids_by_performance[performance_id]):
        return BookingStatusOutput(status=0)

    booking = bookings_by_performance.get(performance_id)
    if booking is not None:
        quantity = quantity_by_performance[performance_id].get(
            (booking.position_type, booking.position_id), 0
        )
        name = name_by_key.get((booking.position_type, booking.position_id), "")
        return BookingStatusOutput(
            status=4 if booking.order < quantity else 3,
            position=PositionRefOutput(id=booking.position_id, name=name),
            at=booking.updated_at,
        )

    booking_request = requests_by_performance.get(performance_id)
    if booking_request is not None:
        return (
            BookingStatusOutput(status=5, at=booking_request.updated_at)
            if booking_request.notbooked_at is not None
            else BookingStatusOutput(status=2, at=booking_request.updated_at)
        )

    return BookingStatusOutput(status=1)


# --- Cast: GET -----------------------------------------------------------


def _get_cast_form_data(
    db: Session, performance: Performance, setup: PerformanceSetupOutput
) -> CastFormData:
    bookings = (
        db.execute(
            select(Booking)
            .where(Booking.performance_id == performance.id)
            .order_by(Booking.position_type, Booking.position_id, Booking.order)
        )
        .scalars()
        .all()
    )
    bookings_by_position: dict[tuple[str, int], list[Booking]] = {}
    for booking in bookings:
        bookings_by_position.setdefault(
            (booking.position_type, booking.position_id), []
        ).append(booking)
    users_by_id = _users_by_id(db, {booking.user_id for booking in bookings})
    primary_voice_by_user = _primary_voice_by_user(
        db, {b.user_id for b in bookings if b.position_type == "choirjobs"}
    )

    sections: dict[PositionType, list[CastSetupItemOutput]] = {
        position_type: [] for position_type in POSITION_TYPES
    }
    setup_groups: tuple[tuple[PositionType, list[PerformancePositionOutput]], ...] = (
        ("instruments", setup.instruments),
        ("voices", setup.voices),
        ("choirjobs", setup.choirjobs),
    )
    for position_type, items in setup_groups:
        for item in items:
            entries = bookings_by_position.get((position_type, item.id), [])
            cast_members = []
            for booking in entries:
                voice_name, voice_order = _choirjob_voice_fields(
                    position_type, booking.user_id, primary_voice_by_user
                )
                cast_members.append(
                    CastMemberOutput(
                        id=booking.user_id,
                        name=_display_name(users_by_id.get(booking.user_id)),
                        fee=booking.fee,
                        voice_name=voice_name,
                        voice_order=voice_order,
                    )
                )
            sections[position_type].append(
                CastSetupItemOutput(id=item.id, name=item.name, cast=cast_members)
            )

    not_booked_requests = (
        db.execute(
            select(BookingRequest).where(
                BookingRequest.performance_id == performance.id,
                BookingRequest.notbooked_at.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    # Legacy's notbooked() GET uses plain User::find() (no withTrashed()),
    # silently skipping soft-deleted users -- unlike the cast list above.
    not_booked_user_ids = {request.user_id for request in not_booked_requests}
    active_users_by_id = _active_users_by_id(db, not_booked_user_ids)
    not_booked = [
        NotBookedOutput(id=user_id, name=_display_name(active_users_by_id[user_id]))
        for user_id in not_booked_user_ids
        if user_id in active_users_by_id
    ]

    return CastFormData(
        cast=CastSectionOutput(
            instruments=sections["instruments"],
            voices=sections["voices"],
            choirjobs=sections["choirjobs"],
        ),
        not_booked=not_booked,
    )


def _get_staff(
    db: Session, performance: Performance, setup: PerformanceSetupOutput
) -> StaffSectionOutput:
    keys: dict[PositionType, set[int]] = {
        "instruments": {item.id for item in setup.instruments},
        "voices": {item.id for item in setup.voices},
        "choirjobs": {item.id for item in setup.choirjobs},
    }
    qualified = get_qualified_user_ids_batch(db, keys)
    all_user_ids: set[int] = set()
    for ids in qualified.values():
        all_user_ids |= ids
    users_by_id = _active_users_by_id(db, all_user_ids)

    choirjob_user_ids: set[int] = set()
    for item in setup.choirjobs:
        choirjob_user_ids |= qualified.get(("choirjobs", item.id), set())
    primary_voice_by_user = _primary_voice_by_user(db, choirjob_user_ids)

    requesting_user_ids = set(
        db.execute(
            select(BookingRequest.user_id).where(
                BookingRequest.performance_id == performance.id
            )
        )
        .scalars()
        .all()
    )

    sections: dict[PositionType, list[StaffItemOutput]] = {
        position_type: [] for position_type in POSITION_TYPES
    }
    setup_groups: tuple[tuple[PositionType, list[PerformancePositionOutput]], ...] = (
        ("instruments", setup.instruments),
        ("voices", setup.voices),
        ("choirjobs", setup.choirjobs),
    )
    for position_type, items in setup_groups:
        for item in items:
            requesting: list[BookableUserOutput] = []
            other: list[BookableUserOutput] = []
            # Legacy sorts these implicitly via User's global
            # OrderBySurnameGivenname scope (Performance::staff() itself
            # has no explicit orderBy) -- qualified user ids come out of a
            # plain set here, so the sort has to happen explicitly.
            candidates = sorted(
                (
                    user
                    for user_id in qualified.get((position_type, item.id), set())
                    if (user := users_by_id.get(user_id)) is not None
                ),
                key=lambda user: (user.surname, user.givenname),
            )
            for user in candidates:
                bucket = requesting if user.id in requesting_user_ids else other
                voice_name, voice_order = _choirjob_voice_fields(
                    position_type, user.id, primary_voice_by_user
                )
                bucket.append(
                    BookableUserOutput(
                        id=user.id,
                        name=_display_name(user),
                        voice_name=voice_name,
                        voice_order=voice_order,
                    )
                )
            sections[position_type].append(
                StaffItemOutput(
                    id=item.id,
                    name=item.name,
                    bookable=BookableGroupOutput(requesting=requesting, other=other),
                )
            )

    return StaffSectionOutput(
        instruments=sections["instruments"],
        voices=sections["voices"],
        choirjobs=sections["choirjobs"],
    )


def _popular_for_position(
    db: Session,
    performance_ids: list[int],
    position_type: PositionType,
    position_id: int,
) -> PopularItemOutput:
    rows = db.execute(
        select(Booking.user_id, Booking.updated_at, Performance.schedule)
        .join(Performance, Performance.id == Booking.performance_id)
        .where(
            Booking.performance_id.in_(performance_ids),
            Booking.position_type == position_type,
            Booking.position_id == position_id,
        )
    ).all()
    if not rows:
        return PopularItemOutput(frequent=[], recent=[])

    users_by_id = _active_users_by_id(db, {row.user_id for row in rows})

    counts: dict[int, int] = {}
    for row in rows:
        if row.user_id in users_by_id:
            counts[row.user_id] = counts.get(row.user_id, 0) + 1
    frequent_ids = sorted(counts, key=lambda uid: counts[uid], reverse=True)[:10]
    frequent = [
        PopularFrequentUserOutput(
            id=uid, name=_display_name(users_by_id[uid]), total=counts[uid]
        )
        for uid in frequent_ids
    ]

    seen: set[int] = set()
    recent: list[PopularRecentUserOutput] = []
    # Naive datetime.min, deliberately without tzinfo: our DateTime columns
    # round-trip every value as naive regardless of how it was written
    # (see app.core.datetime_utils.ensure_tz_aware for the same round-trip
    # caveat elsewhere) -- a tz-aware fallback would raise on comparison
    # against the real (naive) `updated_at` values instead of just sorting
    # last.
    epoch = datetime.min  # noqa: DTZ901
    for row in sorted(rows, key=lambda r: r.updated_at or epoch, reverse=True):
        if row.user_id in seen or row.user_id not in users_by_id:
            continue
        seen.add(row.user_id)
        recent.append(
            PopularRecentUserOutput(
                id=row.user_id,
                name=_display_name(users_by_id[row.user_id]),
                booked=row.schedule,
            )
        )
        if len(recent) >= 10:
            break

    return PopularItemOutput(frequent=frequent, recent=recent)


def _get_popular(db: Session, performance: Performance) -> PopularSectionOutput:
    """Port of Ordinariumwork::popularBookings() -- iterates the
    ORDINARIUMWORK's own Instrument/Voice setup (NOT the performance's own
    position configuration) across ALL of that Ordinariumwork's PAST
    performances. Choirjobs are always empty: Legacy's own
    `ordinariumwork_positions` CHECK constraint excludes 'choirjobs'
    entirely, so that branch is structurally always empty (see
    app.db.models.ordinariumwork_position.OrdinariumworkPosition)."""
    ow_setup = ordinariumwork_service.get_setup(db, performance.ordinariumwork_id)
    past_performance_ids = list(
        db.execute(
            select(Performance.id).where(
                Performance.ordinariumwork_id == performance.ordinariumwork_id,
                Performance.schedule < local_now(),
            )
        )
        .scalars()
        .all()
    )

    instruments_popular: dict[int, PopularItemOutput] = {}
    voices_popular: dict[int, PopularItemOutput] = {}
    if past_performance_ids:
        for item in ow_setup.instruments:
            instruments_popular[item.id] = _popular_for_position(
                db, past_performance_ids, "instruments", item.id
            )
        for item in ow_setup.voices:
            voices_popular[item.id] = _popular_for_position(
                db, past_performance_ids, "voices", item.id
            )

    return PopularSectionOutput(
        instruments=instruments_popular, voices=voices_popular, choirjobs={}
    )


def get_cast_page(db: Session, performance_id: int) -> PerformanceCastPageResponse:
    performance = _get_performance_or_404(db, performance_id)
    _ensure_not_past(performance)
    detail = performance_service.get_performance_detail(db, performance_id)
    setup = detail.setup

    form_data = _get_cast_form_data(db, performance, setup)
    staff = _get_staff(db, performance, setup)
    popular = _get_popular(db, performance)
    fees = fee_service.list_fees(db)

    return PerformanceCastPageResponse(
        id=detail.id,
        ordinariumwork_name=detail.ordinariumwork_name,
        ordinariumwork_artist_name=detail.ordinariumwork_artist_name,
        artist_name=detail.artist_name,
        schedule=detail.schedule,
        rehearsals=detail.rehearsals,
        location=detail.location,
        demanding_proprium=detail.demanding_proprium,
        setup=setup,
        staff=staff,
        form_data=form_data,
        fees=fees,
        popular=popular,
    )


# --- Cast: SAVE (the diff/log engine) ---------------------------------------


def _booking_log(
    db: Session,
    performance_id: int,
    *,
    user_id: int,
    booking_type: Literal["book", "unbook"],
    position_type: PositionType,
    position_id: int,
    fee: int,
) -> None:
    now = datetime.now(UTC)
    db.add(
        BookingLog(
            performance_id=performance_id,
            user_id=user_id,
            booking_type=booking_type,
            position_type=position_type,
            position_id=position_id,
            fee=fee,
            created_at=now,
            updated_at=now,
        )
    )


def _diff_cast_transitions(
    old_cast: list[CastEntry],
    new_cast: list[CastEntry],
    quantity: int,
    old_quantity: int | None,
) -> list[tuple[int, Literal["book", "unbook"], int]]:
    """Pure decision logic behind Performance::saveCastItem()'s book/unbook
    log entries -- deliberately separated from _save_cast_item's DB writes
    so both halves stay independently readable (and this half independently
    unit-testable without touching the database at all)."""
    old_ids = [user_id for user_id, _fee in old_cast]
    new_ids = [user_id for user_id, _fee in new_cast]
    reference_quantity = old_quantity if old_quantity is not None else quantity
    transitions: list[tuple[int, Literal["book", "unbook"], int]] = []

    # 1. entries that dropped out entirely
    for user_id, fee in old_cast:
        if user_id not in new_ids:
            transitions.append((user_id, "unbook", fee))

    # 2. evaluate the new order against the old one
    for index, (user_id, fee) in enumerate(new_cast):
        old_index = old_ids.index(user_id) if user_id in old_ids else None
        if old_index is None:
            # brand new entry -- landing in a regular slot books it,
            # landing in a standby slot logs 'unbook' (Legacy's own,
            # intentionally counter-intuitive naming for "not currently
            # regular").
            transitions.append((user_id, "book" if index < quantity else "unbook", fee))
            continue
        was_regular = old_index < reference_quantity
        if was_regular and index >= quantity:
            transitions.append((user_id, "unbook", fee))
        elif not was_regular and index < quantity:
            transitions.append((user_id, "book", fee))

    return transitions


def _save_cast_item(
    db: Session,
    performance_id: int,
    position_type: PositionType,
    position_id: int,
    *,
    new_cast: list[CastEntry] | None,
    old_quantity: int | None,
) -> None:
    """1:1 port of Performance::saveCastItem() -- the append-only diff/log
    engine behind every cast mutation (Schritt 6 plan's "Exakte
    Legacy-Business-Logik" section specifies the algorithm this mirrors
    line for line)."""
    old_bookings = (
        db.execute(
            select(Booking)
            .where(
                Booking.performance_id == performance_id,
                Booking.position_type == position_type,
                Booking.position_id == position_id,
            )
            .order_by(Booking.order)
        )
        .scalars()
        .all()
    )
    old_cast: list[CastEntry] = [
        (booking.user_id, booking.fee) for booking in old_bookings
    ]

    def _delete_position_bookings() -> None:
        db.execute(
            delete(Booking).where(
                Booking.performance_id == performance_id,
                Booking.position_type == position_type,
                Booking.position_id == position_id,
            )
        )

    if new_cast is None:
        _delete_position_bookings()
        for user_id, fee in old_cast:
            _booking_log(
                db,
                performance_id,
                user_id=user_id,
                booking_type="unbook",
                position_type=position_type,
                position_id=position_id,
                fee=fee,
            )
        db.flush()
        return

    quantity = _quantities_for_performance(db, performance_id).get(
        (position_type, position_id), 0
    )
    for user_id, booking_type, fee in _diff_cast_transitions(
        old_cast, new_cast, quantity, old_quantity
    ):
        _booking_log(
            db,
            performance_id,
            user_id=user_id,
            booking_type=booking_type,
            position_type=position_type,
            position_id=position_id,
            fee=fee,
        )

    # recreate from scratch -- order becomes the array index
    _delete_position_bookings()
    now = datetime.now(UTC)
    for order, (user_id, fee) in enumerate(new_cast):
        # Enforce UNIQUE(performance_id, user_id) app-side: moving someone
        # to a new position auto-unbooks them from wherever else they
        # were booked on this performance.
        db.execute(
            delete(Booking).where(
                Booking.performance_id == performance_id, Booking.user_id == user_id
            )
        )
        db.add(
            Booking(
                performance_id=performance_id,
                user_id=user_id,
                position_type=position_type,
                position_id=position_id,
                fee=fee,
                order=order,
                created_at=now,
                updated_at=now,
            )
        )
    # Flush (not commit) so the NEXT position processed in the same
    # _apply_cast() call sees these rows when it runs its own
    # "delete all bookings of this user" step above -- SessionLocal has
    # autoflush=False, so without this, a user moved from position A to B
    # within the same save_cast() call could end up with rows at BOTH
    # positions, violating bookings' (performance_id, user_id) uniqueness.
    db.flush()


def _apply_cast(
    db: Session,
    performance: Performance,
    setup: PerformanceSetupOutput,
    cast_data: CastSectionInput,
    old_quantities: dict[tuple[PositionType, int], int] | None = None,
) -> None:
    cast_groups: tuple[
        tuple[PositionType, list[PerformancePositionOutput], list[CastSetupItemInput]],
        ...,
    ] = (
        ("instruments", setup.instruments, cast_data.instruments),
        ("voices", setup.voices, cast_data.voices),
        ("choirjobs", setup.choirjobs, cast_data.choirjobs),
    )
    for position_type, setup_items, payload_items in cast_groups:
        payload_by_id = {item.id: item.cast for item in payload_items}
        for setup_item in setup_items:
            payload_cast = payload_by_id.get(setup_item.id)
            entries: list[CastEntry] | None = (
                None
                if payload_cast is None
                else [(member.id, member.fee) for member in payload_cast]
            )
            old_quantity = (
                old_quantities.get((position_type, setup_item.id))
                if old_quantities is not None
                else None
            )
            _save_cast_item(
                db,
                performance.id,
                position_type,
                setup_item.id,
                new_cast=entries,
                old_quantity=old_quantity,
            )


def _apply_notbooked(db: Session, performance: Performance, ids: list[int]) -> None:
    """Port of Performance::notbooked()'s SET branch -- MUST run after
    _apply_cast(), it reads `bookings` post-mutation to exclude anyone who
    ended up actually cast from the "rejected" list."""
    db.execute(
        update(BookingRequest)
        .where(BookingRequest.performance_id == performance.id)
        .values(notbooked_at=None)
    )
    booked_user_ids = set(
        db.execute(
            select(Booking.user_id).where(Booking.performance_id == performance.id)
        )
        .scalars()
        .all()
    )
    notbooked_ids = [user_id for user_id in ids if user_id not in booked_user_ids]
    if notbooked_ids:
        db.execute(
            update(BookingRequest)
            .where(
                BookingRequest.performance_id == performance.id,
                BookingRequest.user_id.in_(notbooked_ids),
            )
            .values(notbooked_at=datetime.now(UTC))
        )


def save_cast(db: Session, performance_id: int, data: CastSaveRequest) -> CastFormData:
    performance = _get_performance_or_404(db, performance_id)
    _ensure_not_past(performance)
    setup = performance_service.get_setup(db, performance_id)
    _apply_cast(db, performance, setup, data.cast)
    _apply_notbooked(db, performance, [entry.id for entry in data.not_booked])
    db.commit()
    return _get_cast_form_data(db, performance, setup)


def reconcile_setup_change(
    db: Session,
    performance_id: int,
    removed_keys: set[tuple[str, int]],
    old_quantities: dict[tuple[str, int], int],
) -> None:
    """Port of Performance::setup()'s cast-reconciliation step, called from
    performance_service.update_performance() right after `_sync_positions`
    (Schritt 6 plan A.5b) -- purges bookings on removed positions, then
    re-evaluates promote/demote on
    every remaining position against its OLD quantity. `removed_keys`/
    `old_quantities` are `str`-keyed (not the `PositionType` Literal) since
    they originate from `PerformancePosition.position_type`, a DB column
    (see _position_names_batch's docstring for the same reasoning)."""
    for position_type, position_id in removed_keys:
        _save_cast_item(
            db,
            performance_id,
            cast("PositionType", position_type),
            position_id,
            new_cast=None,
            old_quantity=None,
        )

    performance = _get_performance_or_404(db, performance_id)
    setup = performance_service.get_setup(db, performance_id)
    current_cast = _get_cast_form_data(db, performance, setup).cast
    cast_groups: tuple[tuple[PositionType, list[CastSetupItemOutput]], ...] = (
        ("instruments", current_cast.instruments),
        ("voices", current_cast.voices),
        ("choirjobs", current_cast.choirjobs),
    )
    for position_type, items in cast_groups:
        for item in items:
            old_quantity = old_quantities.get((position_type, item.id))
            entries: list[CastEntry] = [(member.id, member.fee) for member in item.cast]
            _save_cast_item(
                db,
                performance_id,
                position_type,
                item.id,
                new_cast=entries,
                old_quantity=old_quantity,
            )


# --- Self-service (User's own booking-status toggle) ------------------------


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
    schedules via `BackgroundTasks.add_task(mailer.send_...)` -- returns
    None if there is nothing to send. The service layer stays framework-
    agnostic (no FastAPI import), matching every other service module in
    this codebase (e.g. auth_service.py's request_password_reset(), whose
    router caller decides whether/how to schedule the background task)."""
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


def cancel_auth_user_booking(db: Session, performance_id: int, user_id: int) -> None:
    """Port of cancelAuthUserBooking() -- rebuilds the remaining cast list
    for the user's (former) position (without them) and re-runs it through
    _save_cast_item, which automatically promotes the next standby entry
    and logs accordingly."""
    booking = db.execute(
        select(Booking).where(
            Booking.performance_id == performance_id, Booking.user_id == user_id
        )
    ).scalar_one_or_none()
    if booking is None:
        return

    remaining = (
        db.execute(
            select(Booking)
            .where(
                Booking.performance_id == performance_id,
                Booking.position_type == booking.position_type,
                Booking.position_id == booking.position_id,
                Booking.id != booking.id,
            )
            .order_by(Booking.order)
        )
        .scalars()
        .all()
    )
    entries: list[CastEntry] = [(row.user_id, row.fee) for row in remaining]
    _save_cast_item(
        db,
        performance_id,
        cast("PositionType", booking.position_type),
        booking.position_id,
        new_cast=entries,
        old_quantity=None,
    )


def _request_booking(db: Session, performance_id: int, user_id: int) -> None:
    existing = db.execute(
        select(BookingRequest).where(
            BookingRequest.performance_id == performance_id,
            BookingRequest.user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BookingRequestAlreadyExistsError
    now = datetime.now(UTC)
    db.add(
        BookingRequest(
            performance_id=performance_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
    )


def _cancel_booking_or_request(
    db: Session, performance: Performance, user: User, current: BookingStatusOutput
) -> BookedOrStandbyCanceledNotification | None:
    notification = (
        _build_canceled_notification(db, performance, user, current)
        if current.status in (3, 4)
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
    db: Session, performance_id: int, user: User
) -> tuple[BookingStatusOutput, BookedOrStandbyCanceledNotification | None]:
    """Port of PerformanceController::changeUserRequestStatus() -- takes no
    client-provided target status (unlike this plan's original draft
    schema): the server recomputes the CURRENT status itself via
    user_booking_status() and dispatches on that, exactly like Legacy's
    `switch ($performance->auth_user_booking['status'])`. A client can
    never dictate an arbitrary transition (this endpoint's own earlier
    draft schema allowed one and was corrected before implementation).

    Returns the notification descriptor (or None) for the ROUTER to
    enqueue via `arq_pool.enqueue_job(..., notification.disponent_emails,
    notification.canceling_user_name, notification.entry)` -- the
    descriptor captures the OLD status before this function's own
    db.commit() below, exactly like Legacy's Mail::send() call preceding
    the switch."""
    performance = _get_performance_or_404(db, performance_id)
    _ensure_not_past(performance)
    current = user_booking_status(db, performance, user.id)

    notification: BookedOrStandbyCanceledNotification | None = None
    if current.status == 1:
        _request_booking(db, performance_id, user.id)
    elif current.status in (2, 3, 4, 5):
        notification = _cancel_booking_or_request(db, performance, user, current)
    # status 0 (not bookable): Legacy's switch has no matching case --
    # a silent no-op, replicated here the same way.

    db.commit()
    return user_booking_status(db, performance, user.id), notification


# --- Billing -----------------------------------------------------------------


def _truncate_cast(
    items: list[CastSetupItemOutput], setup_items: list[PerformancePositionOutput]
) -> list[CastSetupItemOutput]:
    quantity_by_id = {item.id: item.quantity for item in setup_items}
    return [
        CastSetupItemOutput(
            id=item.id, name=item.name, cast=item.cast[: quantity_by_id[item.id]]
        )
        for item in items
    ]


def _booked_cast(
    db: Session, performance: Performance, setup: PerformanceSetupOutput
) -> CastSectionOutput:
    """Port of Performance::bookedCast() -- the full cast list truncated to
    each position's quantity (drops standby entries), used by billing
    (unbooked-slot pricing) and MessageToCast (only actually-booked users
    are message recipients)."""
    full_cast = _get_cast_form_data(db, performance, setup).cast
    return CastSectionOutput(
        instruments=_truncate_cast(full_cast.instruments, setup.instruments),
        voices=_truncate_cast(full_cast.voices, setup.voices),
        choirjobs=_truncate_cast(full_cast.choirjobs, setup.choirjobs),
    )


def _billing_by_item(
    setup_item: PerformancePositionOutput,
    cast_item: CastSetupItemOutput,
    default_fee: int,
) -> BillingItemOutput:
    positions: list[BillingPositionOutput] = []
    total = 0
    for index in range(setup_item.quantity):
        if index < len(cast_item.cast):
            member = cast_item.cast[index]
            positions.append(
                BillingPositionOutput(id=member.id, name=member.name, fee=member.fee)
            )
            total += member.fee
        else:
            positions.append(
                BillingPositionOutput(id=None, name="N. N.", fee=default_fee)
            )
            total += default_fee
    return BillingItemOutput(
        id=setup_item.id,
        name=setup_item.name,
        quantity=setup_item.quantity,
        positions=positions,
        sum=total,
    )


def _billing_by_type(
    setup_items: list[PerformancePositionOutput],
    cast_items: list[CastSetupItemOutput],
    default_fee: int,
) -> BillingTypeOutput:
    cast_by_id = {item.id: item for item in cast_items}
    items: list[BillingItemOutput] = []
    total_sum = 0
    total_count = 0
    for setup_item in setup_items:
        billed = _billing_by_item(setup_item, cast_by_id[setup_item.id], default_fee)
        items.append(billed)
        total_sum += billed.sum
        total_count += billed.quantity
    return BillingTypeOutput(items=items, sum=total_sum, count=total_count)


def _org_fee(instrument_count: int, choirjob_count: int) -> BillingOrgfeeOutput:
    instruments_fee = 0
    if instrument_count > _INSTRUMENTS_ORGFEE_TIER1_THRESHOLD:
        instruments_fee = _INSTRUMENTS_ORGFEE_TIER1
    if instrument_count > _INSTRUMENTS_ORGFEE_TIER2_THRESHOLD:
        instruments_fee = _INSTRUMENTS_ORGFEE_TIER2  # replaces, not adds to, tier 1

    choirjobs_fee = 0
    if choirjob_count > _CHOIRJOBS_ORGFEE_THRESHOLD:
        choirjobs_fee = _CHOIRJOBS_ORGFEE

    return BillingOrgfeeOutput(
        instruments=instruments_fee,
        choirjobs=choirjobs_fee,
        sum=instruments_fee + choirjobs_fee,
    )


def get_billing(
    db: Session, performance_id: int, current_user: User
) -> PerformanceBillingResponse:
    """No past-lock -- Legacy's `billing` policy checks only the `billing`
    role, unlike `cast`/`maintain` (Schritt 6 plan, router table)."""
    performance = _get_performance_or_404(db, performance_id)
    detail = performance_service.get_performance_detail(db, performance_id)
    setup = detail.setup
    booked_cast = _booked_cast(db, performance, setup)

    instruments_bill = _billing_by_type(
        setup.instruments, booked_cast.instruments, performance.instrument_defaultfee
    )
    voices_bill = _billing_by_type(
        setup.voices, booked_cast.voices, performance.voice_defaultfee
    )
    choirjobs_bill = _billing_by_type(
        setup.choirjobs, booked_cast.choirjobs, performance.choirjob_defaultfee
    )
    orgfee = _org_fee(instruments_bill.count, choirjobs_bill.count)
    extracost = BillingExtracostOutput(
        amount=performance.extracost_amount or 0,
        description=performance.extracost_description or "",
    )
    total = (
        instruments_bill.sum
        + voices_bill.sum
        + choirjobs_bill.sum
        + orgfee.sum
        + extracost.amount
    )

    user_booking = user_booking_status(db, performance, current_user.id)
    short = _to_short_output(detail, user_booking)
    return PerformanceBillingResponse(
        **short.model_dump(),
        billing=BillingOutput(
            instruments=instruments_bill,
            voices=voices_bill,
            choirjobs=choirjobs_bill,
            orgfee=orgfee,
            extracost=extracost,
            sum=total,
        ),
    )


# --- RequestsAndBookings -----------------------------------------------------


def get_requests_and_bookings(
    db: Session, performance_id: int, current_user: User
) -> PerformanceRequestsAndBookingsResponse:
    performance = _get_performance_or_404(db, performance_id)
    _ensure_not_past(performance)
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
    ordered_ids: list[int] = []
    seen: set[int] = set()
    for user_id in booked_user_ids + requesting_user_ids:
        if user_id not in seen:
            seen.add(user_id)
            ordered_ids.append(user_id)

    statuses = user_booking_status_batch(db, performance, ordered_ids)
    users_by_id = _users_by_id(db, set(ordered_ids))
    entries = [
        RequestOrBookingEntryOutput(
            id=user_id,
            name=_display_name(users_by_id.get(user_id)),
            status=statuses[user_id],
        )
        for user_id in ordered_ids
    ]

    user_booking = user_booking_status(db, performance, current_user.id)
    short = _to_short_output(detail, user_booking)
    return PerformanceRequestsAndBookingsResponse(**short.model_dump(), entries=entries)


# --- Selfadmin-Support (Schritt 7) --------------------------------------------


def get_upcoming_requests_and_bookings_for_user(
    db: Session, user_id: int, *, upcoming_only: bool = True
) -> list[PerformanceShortOutput]:
    """1:1 Legacy's `User::requestsAndBookings($upcomingOnly, false)`: every
    Performance the user has either a confirmed Booking for, or (failing
    that) an open BookingRequest for -- Bookings take precedence on the
    rare case both exist for the same performance, matching Legacy's own
    "booked ids first, then requesting ids not already covered" de-dup
    order (no filter on BookingRequest.notbooked_at -- Legacy includes
    rejected requests here too).

    `upcoming_only` defaults to True (Legacy's Selfadmin/SupportController
    calls `->requestsAndBookings(true)`), but the System-admin per-user
    "Anfragen und Buchungen" view (Baustelle 1's `GET /users/{id}/requests-
    and-bookings`) calls Legacy's `System\\UserController::
    requestsAndBookings()`, which uses the bare, ALL-history default
    (`$upcomingOnly = false`). Generic on `user_id` (not necessarily the
    caller) so this one function backs both callers."""
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
    ordered_ids: list[int] = []
    seen: set[int] = set()
    for performance_id in booked_ids + requested_ids:
        if performance_id not in seen:
            seen.add(performance_id)
            ordered_ids.append(performance_id)
    if not ordered_ids:
        return []

    performances = (
        db.execute(
            select(Performance)
            .where(Performance.id.in_(ordered_ids))
            .order_by(Performance.schedule)
        )
        .scalars()
        .all()
    )
    batch = performance_service.load_performance_batch_data(db, performances)
    user_booking_by_performance = user_booking_status_for_performances(
        db, list(performances), user_id, keep_past_status=not upcoming_only
    )

    return [
        PerformanceShortOutput(
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
        for performance in performances
    ]


# --- MessageToCast ------------------------------------------------------------


def get_message_to_cast_page(
    db: Session, performance_id: int, current_user: User
) -> PerformanceMessageToCastResponse:
    """No past-lock -- Legacy's MessageToCastRequest authorizes against
    `Performance::class` (no instance), so `maintain`'s object-level
    past-check never triggers here, unlike requestsAndBookings() which
    authorizes against the actual `$performance` instance. Replicated as
    an intentional Legacy quirk, not "fixed"."""
    performance = _get_performance_or_404(db, performance_id)
    detail = performance_service.get_performance_detail(db, performance_id)
    setup = detail.setup
    booked_cast = _booked_cast(db, performance, setup)
    user_booking = user_booking_status(db, performance, current_user.id)
    short = _to_short_output(detail, user_booking)
    return PerformanceMessageToCastResponse(
        **short.model_dump(), booked_cast=booked_cast
    )


def _ordered_recipient_ids(
    booked_cast: CastSectionOutput,
    position_type: PositionType | None,
    position_id: int | None,
) -> list[int]:
    """Legacy order: instruments, then voices, then choirjobs -- each
    item's cast is already sorted by position order + booking order (see
    Performance::cast()/bookedCast())."""
    if position_type is not None:
        section = getattr(booked_cast, position_type)
        item = next((entry for entry in section if entry.id == position_id), None)
        return [member.id for member in item.cast] if item is not None else []

    ordered_ids: list[int] = []
    seen: set[int] = set()
    for section in (booked_cast.instruments, booked_cast.voices, booked_cast.choirjobs):
        for item in section:
            for member in item.cast:
                if member.id in seen:
                    continue
                seen.add(member.id)
                ordered_ids.append(member.id)
    return ordered_ids


def get_message_recipients(
    db: Session,
    performance_id: int,
    position_type: PositionType | None,
    position_id: int | None,
) -> list[MessageRecipientOutput]:
    performance = _get_performance_or_404(db, performance_id)
    setup = performance_service.get_setup(db, performance_id)
    booked_cast = _booked_cast(db, performance, setup)

    ordered_ids = _ordered_recipient_ids(booked_cast, position_type, position_id)
    users_by_id = _users_by_id(db, set(ordered_ids))
    return [
        MessageRecipientOutput(
            id=user.id,
            surname=user.surname,
            givenname=user.givenname,
            has_email=user.email_verified_at is not None,
            email=user.email if user.email_verified_at is not None else None,
            phone=user.phone,
        )
        for user_id in ordered_ids
        if (user := users_by_id.get(user_id)) is not None
    ]


def send_message_to_cast(
    db: Session, performance_id: int, sender: User, data: SendMessageRequest
) -> tuple[list[str], str, str]:
    """The MessageToCast send bugfix -- Legacy's "Nachricht senden" button
    posted to a GET-only route (guaranteed HTTP 405, the feature was
    never reachable). This
    builds a real, working send on top of the same mailer/template
    infrastructure Legacy already had sitting unused for exactly this
    purpose (`user_message.blade.php`).

    Returns (to_emails, sender_name, message) for the ROUTER to schedule
    via `BackgroundTasks.add_task(mailer.send_user_message_email, ...)` --
    the service layer stays framework-agnostic (no FastAPI import)."""
    _get_performance_or_404(db, performance_id)
    users_by_id = _users_by_id(db, set(data.recipient_ids))
    to_emails = [
        user.email
        for user in users_by_id.values()
        if user.email is not None and user.email_verified_at is not None
    ]
    if not to_emails:
        raise MessageRecipientsEmptyError
    return to_emails, label_for_name(sender.surname, sender.givenname), data.message
