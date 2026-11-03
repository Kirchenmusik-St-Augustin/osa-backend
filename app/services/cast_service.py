import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import delete, select, update

from app.core.datetime_utils import local_now
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.performance import Performance
from app.db.models.user_position import UserPosition
from app.db.models.voice import Voice
from app.schemas.base import IdNameOutput
from app.schemas.booking import (
    BookableGroupOutput,
    BookableUserOutput,
    CastFormData,
    CastMemberOutput,
    CastSaveRequest,
    CastSectionInput,
    CastSectionOutput,
    CastSetupItemInput,
    CastSetupItemOutput,
    PerformanceCastPageResponse,
    PopularFrequentUserOutput,
    PopularItemOutput,
    PopularRecentUserOutput,
    PopularSectionOutput,
    StaffItemOutput,
    StaffSectionOutput,
)
from app.services import fee_service, ordinariumwork_service, performance_service
from app.services.booking_common import (
    display_name,
    ensure_not_past,
    get_performance_or_404,
    load_active_users_by_id,
    load_users_by_id,
    quantities_for_performance,
)
from app.services.position_types import (
    POSITION_TYPES,
    PositionType,
    position_column,
    position_key,
    position_kwargs,
)
from app.services.user_position_service import get_qualified_user_ids_batch

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models.user import User
    from app.schemas.performance import (
        PerformancePositionOutput,
        PerformanceSetupOutput,
    )


# (user_id, fee) -- the internal exchange shape save_cast_item's diff engine
# works with, decoupled from the CastMemberInput/-Output Pydantic schemas
# that only exist at the HTTP boundary (reconcile_setup_change and
# cancel_auth_user_booking build these from ORM rows, not request bodies).
CastEntry = tuple[uuid.UUID, int]


def _primary_voice_by_user(
    db: Session, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Voice]:
    """Each user's lowest-`Voice.order` assigned Voice (their "primary"
    voice for choirjob auto-sort) via UserPosition -- N+1-safe: exactly one
    UserPosition query + one Voice query, regardless of how many user_ids
    come in. A user CAN hold multiple `voices`-type UserPosition rows (no
    DB constraint prevents it -- UserPosition's only unique constraint is
    the full (user_id, instrument_id, voice_id, choirjob_id) tuple); the
    lowest-`order` one wins, matching performance_service.get_setup()'s own
    `.order_by(Voice.order, Voice.id)` canonical-ordering idiom."""
    if not user_ids:
        return {}
    voice_ids_by_user: dict[uuid.UUID, set[uuid.UUID]] = {}
    rows = db.execute(
        select(UserPosition.user_id, UserPosition.voice_id).where(
            UserPosition.user_id.in_(user_ids),
            UserPosition.voice_id.is_not(None),
        )
    ).all()
    for user_id, voice_id in rows:
        # voice_id is statically `uuid.UUID | None` (the WHERE clause's
        # `is_not(None)` is a runtime-only guarantee, not one the type
        # checker can see through) -- narrow explicitly rather than lean on
        # a redundant-in-practice branch never actually taken.
        if voice_id is None:
            continue
        voice_ids_by_user.setdefault(user_id, set()).add(voice_id)
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
    position_type: PositionType,
    user_id: uuid.UUID,
    primary_voice_by_user: dict[uuid.UUID, Voice],
) -> tuple[str | None, int | None]:
    """Voice fields only ever populated for choirjobs -- instruments/voices
    cast members and candidates keep both fields None."""
    if position_type != "choirjobs":
        return None, None
    voice = primary_voice_by_user.get(user_id)
    return (voice.name, voice.order) if voice is not None else (None, None)


def _get_cast_form_data(
    db: Session, performance: Performance, setup: PerformanceSetupOutput
) -> CastFormData:
    bookings = (
        db.execute(
            select(Booking)
            .where(Booking.performance_id == performance.id)
            # Grouping order is re-derived by the Python dict-bucketing
            # below regardless of row adjacency -- only the per-key `.order`
            # sub-ordering is actually load-bearing (it determines cast vs.
            # standby membership once bucketed).
            .order_by(Booking.order)
        )
        .scalars()
        .all()
    )
    bookings_by_position: dict[tuple[PositionType, uuid.UUID], list[Booking]] = {}
    for booking in bookings:
        bookings_by_position.setdefault(position_key(booking), []).append(booking)
    users_by_id = load_users_by_id(db, {booking.user_id for booking in bookings})
    primary_voice_by_user = _primary_voice_by_user(
        db, {b.user_id for b in bookings if b.choirjob_id is not None}
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
            cast_members: list[CastMemberOutput] = []
            for booking in entries:
                voice_name, voice_order = _choirjob_voice_fields(
                    position_type, booking.user_id, primary_voice_by_user
                )
                cast_members.append(
                    CastMemberOutput(
                        id=booking.user_id,
                        name=display_name(users_by_id.get(booking.user_id)),
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
    # Soft-deleted users are silently skipped here -- unlike the cast list
    # above.
    not_booked_user_ids = {request.user_id for request in not_booked_requests}
    active_users_by_id = load_active_users_by_id(db, not_booked_user_ids)
    not_booked = [
        IdNameOutput(id=user_id, name=display_name(active_users_by_id[user_id]))
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
    keys: dict[PositionType, set[uuid.UUID]] = {
        "instruments": {item.id for item in setup.instruments},
        "voices": {item.id for item in setup.voices},
        "choirjobs": {item.id for item in setup.choirjobs},
    }
    qualified = get_qualified_user_ids_batch(db, keys)
    all_user_ids: set[uuid.UUID] = set()
    for ids in qualified.values():
        all_user_ids |= ids
    users_by_id = load_active_users_by_id(db, all_user_ids)

    choirjob_user_ids: set[uuid.UUID] = set()
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
            # Qualified user ids come out of a plain set here, so the sort
            # by (surname, givenname) has to happen explicitly.
            candidates: list[User] = sorted(
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
                        name=display_name(user),
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
    performance_ids: list[uuid.UUID],
    position_type: PositionType,
    position_id: uuid.UUID,
) -> PopularItemOutput:
    rows = db.execute(
        # Booking.id, not created_at/updated_at: a Booking row is always
        # deleted and recreated by save_cast_item's diff engine, never
        # updated in place, so the set_updated_at() trigger never fires
        # on it (updated_at stays NULL for every row). created_at would
        # work in principle, but Postgres' now() (the DEFAULT behind it)
        # is transaction-constant, not statement-constant -- every
        # Booking row inserted within the same transaction gets the
        # identical created_at value, which loses "who was booked most
        # recently" whenever several bookings happen close together (a
        # single Cast-page save iterates multiple positions in one
        # transaction). Booking.id is UUIDv7 -- time-ordered with real
        # sub-millisecond precision (verified: consecutive uuidv7() calls
        # within one statement come back in strict generation order), so
        # it is still a valid, timestamp-independent stand-in for
        # insertion order and is never NULL, sorting "most recently
        # booked" correctly regardless of how many bookings landed in the
        # same transaction -- the same property the previous
        # autoincrement-integer id gave, just derived differently.
        select(Booking.id, Booking.user_id, Performance.schedule)
        .join(Performance, Performance.id == Booking.performance_id)
        .where(
            Booking.performance_id.in_(performance_ids),
            position_column(Booking, position_type) == position_id,
        )
    ).all()
    if not rows:
        return PopularItemOutput(frequent=[], recent=[])

    users_by_id = load_active_users_by_id(db, {row.user_id for row in rows})

    counts: dict[uuid.UUID, int] = {}
    for row in rows:
        if row.user_id in users_by_id:
            counts[row.user_id] = counts.get(row.user_id, 0) + 1
    frequent_ids = sorted(counts, key=lambda uid: counts[uid], reverse=True)[:10]
    frequent = [
        PopularFrequentUserOutput(
            id=uid, name=display_name(users_by_id[uid]), total=counts[uid]
        )
        for uid in frequent_ids
    ]

    seen: set[uuid.UUID] = set()
    recent: list[PopularRecentUserOutput] = []
    for row in sorted(rows, key=lambda r: r.id, reverse=True):
        if row.user_id in seen or row.user_id not in users_by_id:
            continue
        seen.add(row.user_id)
        recent.append(
            PopularRecentUserOutput(
                id=row.user_id,
                name=display_name(users_by_id[row.user_id]),
                booked=row.schedule,
            )
        )
        if len(recent) >= 10:
            break

    return PopularItemOutput(frequent=frequent, recent=recent)


def _get_popular(db: Session, performance: Performance) -> PopularSectionOutput:
    """Popular bookings -- iterates the ORDINARIUMWORK's own Instrument/
    Voice setup (NOT the performance's own position configuration) across
    ALL of that Ordinariumwork's PAST performances. Choirjobs are always
    empty: an Ordinariumwork's positions can never include 'choirjobs', so
    that branch is structurally always empty (see
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

    instruments_popular: dict[uuid.UUID, PopularItemOutput] = {}
    voices_popular: dict[uuid.UUID, PopularItemOutput] = {}
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


def get_cast_page(
    db: Session, performance_id: uuid.UUID
) -> PerformanceCastPageResponse:
    performance = get_performance_or_404(db, performance_id)
    ensure_not_past(performance)
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


def _booking_log(
    db: Session,
    performance_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    booking_type: Literal["book", "unbook"],
    position_type: PositionType,
    position_id: uuid.UUID,
    fee: int,
) -> None:
    db.add(
        BookingLog(
            performance_id=performance_id,
            user_id=user_id,
            booking_type=booking_type,
            fee=fee,
            **position_kwargs(position_type, position_id),
        )
    )


def _diff_cast_transitions(
    old_cast: list[CastEntry],
    new_cast: list[CastEntry],
    quantity: int,
    old_quantity: int | None,
) -> list[tuple[uuid.UUID, Literal["book", "unbook"], int]]:
    """Pure decision logic behind save_cast_item's book/unbook
    log entries -- deliberately separated from save_cast_item's DB writes
    so both halves stay independently readable (and this half independently
    unit-testable without touching the database at all)."""
    old_ids = [user_id for user_id, _fee in old_cast]
    new_ids = [user_id for user_id, _fee in new_cast]
    reference_quantity = old_quantity if old_quantity is not None else quantity
    transitions: list[tuple[uuid.UUID, Literal["book", "unbook"], int]] = []

    # 1. entries that dropped out entirely
    for user_id, fee in old_cast:
        if user_id not in new_ids:
            transitions.append((user_id, "unbook", fee))

    # 2. evaluate the new order against the old one
    for index, (user_id, fee) in enumerate(new_cast):
        old_index = old_ids.index(user_id) if user_id in old_ids else None
        if old_index is None:
            # brand new entry -- landing in a regular slot books it,
            # landing in a standby slot logs 'unbook' (deliberately
            # counter-intuitive naming for "not currently regular").
            transitions.append((user_id, "book" if index < quantity else "unbook", fee))
            continue
        was_regular = old_index < reference_quantity
        if was_regular and index >= quantity:
            transitions.append((user_id, "unbook", fee))
        elif not was_regular and index < quantity:
            transitions.append((user_id, "book", fee))

    return transitions


def save_cast_item(
    db: Session,
    performance_id: uuid.UUID,
    position_type: PositionType,
    position_id: uuid.UUID,
    *,
    new_cast: list[CastEntry] | None,
    old_quantity: int | None,
) -> None:
    """The append-only diff/log engine behind every cast mutation: compares
    the old and new cast of one position, logs each transition and
    recreates that position's bookings."""
    booking_position_column = position_column(Booking, position_type)
    old_bookings = (
        db.execute(
            select(Booking)
            .where(
                Booking.performance_id == performance_id,
                booking_position_column == position_id,
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
                booking_position_column == position_id,
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

    quantity = quantities_for_performance(db, performance_id).get(
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
    # Enforce UNIQUE(performance_id, user_id) app-side: moving someone to a
    # new position auto-unbooks them from wherever else they were booked on
    # this performance (one statement for the whole cast).
    if new_cast:
        db.execute(
            delete(Booking).where(
                Booking.performance_id == performance_id,
                Booking.user_id.in_([user_id for user_id, _ in new_cast]),
            )
        )
    for order, (user_id, fee) in enumerate(new_cast):
        db.add(
            Booking(
                performance_id=performance_id,
                user_id=user_id,
                fee=fee,
                order=order,
                **position_kwargs(position_type, position_id),
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
    old_quantities: dict[tuple[PositionType, uuid.UUID], int] | None = None,
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
            save_cast_item(
                db,
                performance.id,
                position_type,
                setup_item.id,
                new_cast=entries,
                old_quantity=old_quantity,
            )


def _apply_notbooked(
    db: Session, performance: Performance, ids: list[uuid.UUID]
) -> None:
    """Marks the given requests as rejected -- MUST run after
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


def save_cast(
    db: Session, performance_id: uuid.UUID, data: CastSaveRequest
) -> CastFormData:
    performance = get_performance_or_404(db, performance_id, lock=True)
    ensure_not_past(performance)
    setup = performance_service.get_setup(db, performance_id)
    _apply_cast(db, performance, setup, data.cast)
    _apply_notbooked(db, performance, [entry.id for entry in data.not_booked])
    db.commit()
    return _get_cast_form_data(db, performance, setup)


def reconcile_setup_change(
    db: Session,
    performance_id: uuid.UUID,
    removed_keys: set[tuple[PositionType, uuid.UUID]],
    old_quantities: dict[tuple[PositionType, uuid.UUID], int],
) -> None:
    """Cast reconciliation after a setup change, called from
    performance_service.update_performance() right after `_sync_positions`
    -- purges bookings on removed positions, then
    re-evaluates promote/demote on every remaining position against its OLD
    quantity."""
    # Locked before the first read of the bookings, see get_performance_or_404.
    performance = get_performance_or_404(db, performance_id, lock=True)
    for position_type, position_id in removed_keys:
        save_cast_item(
            db,
            performance_id,
            position_type,
            position_id,
            new_cast=None,
            old_quantity=None,
        )

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
            save_cast_item(
                db,
                performance_id,
                position_type,
                item.id,
                new_cast=entries,
                old_quantity=old_quantity,
            )


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


def get_booked_cast(
    db: Session, performance: Performance, setup: PerformanceSetupOutput
) -> CastSectionOutput:
    """The full cast list truncated to each position's quantity (drops standby entries),
    used by billing (unbooked-slot pricing) and MessageToCast (only actually-booked
    users are message recipients)."""
    full_cast = _get_cast_form_data(db, performance, setup).cast
    return CastSectionOutput(
        instruments=_truncate_cast(full_cast.instruments, setup.instruments),
        voices=_truncate_cast(full_cast.voices, setup.voices),
        choirjobs=_truncate_cast(full_cast.choirjobs, setup.choirjobs),
    )
